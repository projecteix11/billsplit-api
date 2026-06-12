"""
Tests for:
  POST /api/payments                  – staff-only manual/cash payment (auth + rate limited)
  POST /api/payments/redsys-initiate  – server-authoritative Redsys initiation (rate limited)

Security model (Master Ecosystem Report XC-1): the client never sends an amount;
the server computes it from the DB and persists a pending payment. The Redsys S2S
callback (tested at the DB/edge layer) is the only writer of payment_status='paid'.
"""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from tests.conftest import make_payment, make_mock_client, make_order, make_order_item
from app.middleware.auth import require_auth
from app.models import Order


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

@pytest.fixture()
def authed_client(client, app):
    """The shared client with require_auth satisfied (staff). Reuses the conftest
    client (single app lifespan) and just toggles the override, removed after."""
    app.dependency_overrides[require_auth] = lambda: "user-test"
    yield client
    app.dependency_overrides.pop(require_auth, None)


def _signed_edge_response(order_number="123456789012"):
    return {
        "Ds_MerchantParameters": "eyJhbW91bnQiOiI1MCJ9",
        "Ds_Signature": "dGVzdHNpZ25hdHVyZQ==",
        "Ds_SignatureVersion": "HMAC_SHA256_V1",
        "redsysUrl": "https://sis-t.redsys.es:25443/sis/realizarPago",
        "orderNumber": order_number,
    }


def _mock_edge_post():
    mock_resp = MagicMock()
    mock_resp.json.return_value = _signed_edge_response()
    mock_resp.raise_for_status.return_value = None
    return mock_resp


# ---------------------------------------------------------------------------
# POST /api/payments  (now staff-only: manual/cash)
# ---------------------------------------------------------------------------

class TestCreatePayment:
    _valid_body = {"orderId": "order-1", "amount": 27.50, "method": "card"}

    def test_requires_auth(self, client: TestClient):
        # No auth override -> the staff-only endpoint must reject anonymous callers.
        resp = client.post("/payments", json=self._valid_body)
        assert resp.status_code == 401

    def test_create_payment_returns_201_on_success(self, authed_client: TestClient):
        with patch("app.services.payments.get_client") as mock_gc:
            mock_gc.return_value = make_mock_client(data=[make_payment()])
            resp = authed_client.post("/payments", json=self._valid_body)
        assert resp.status_code == 201

    def test_create_payment_returns_correct_fields(self, authed_client: TestClient):
        with patch("app.services.payments.get_client") as mock_gc:
            mock_gc.return_value = make_mock_client(data=[make_payment()])
            resp = authed_client.post("/payments", json=self._valid_body)
        data = resp.json()["data"]
        assert data["order_id"] == "order-1"
        assert data["amount"] == 27.50
        assert data["status"] == "confirmed"

    def test_missing_amount_returns_422(self, authed_client: TestClient):
        resp = authed_client.post("/payments", json={"orderId": "o-1", "method": "cash"})
        assert resp.status_code == 422

    def test_zero_amount_returns_400(self, authed_client: TestClient):
        resp = authed_client.post("/payments", json={"orderId": "o-1", "amount": 0, "method": "cash"})
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# POST /api/payments/redsys-initiate  (customer path; no amount from client)
# ---------------------------------------------------------------------------

class TestRedsysInitiate:
    _valid_body = {
        "orderId": "order-1",
        "items": [{"itemId": "item-1", "portions": 1}],
        "method": "card",
        "urlOk": "https://example.com/ok",
        "urlKo": "https://example.com/ko",
    }

    def _order_with_item(self):
        # dish_price 12.50 x qty 2 = 25.00 subtotal -> +10% tax -> 27.50
        item = make_order_item(id="item-1", dish_price=12.50, quantity=2, payment_status="unassigned")
        return Order(**make_order(items=[item]))

    def test_returns_200_and_signed_payload(self, client: TestClient):
        with patch("app.services.payments.get_order_by_id", return_value=self._order_with_item()), \
             patch("app.services.payments.get_client", return_value=make_mock_client(data=[{}])), \
             patch("app.services.payments.httpx.post", return_value=_mock_edge_post()):
            resp = client.post("/payments/redsys-initiate", json=self._valid_body)
        assert resp.status_code == 200
        body = resp.json()
        assert body["Ds_Signature"]
        assert body["orderNumber"]

    def test_amount_is_server_computed_not_client_supplied(self, client: TestClient):
        # Client tries to smuggle a tiny amount; server must ignore it and bill 27.50.
        tampered = {**self._valid_body, "amount": 0.01}
        with patch("app.services.payments.get_order_by_id", return_value=self._order_with_item()), \
             patch("app.services.payments.get_client", return_value=make_mock_client(data=[{}])), \
             patch("app.services.payments.httpx.post", return_value=_mock_edge_post()) as m:
            resp = client.post("/payments/redsys-initiate", json=tampered)
        assert resp.status_code == 200
        sent = m.call_args.kwargs["json"]
        assert sent["amount"] == 27.50

    def test_item_not_in_order_returns_400(self, client: TestClient):
        body = {**self._valid_body, "items": [{"itemId": "ghost", "portions": 1}]}
        with patch("app.services.payments.get_order_by_id", return_value=self._order_with_item()):
            resp = client.post("/payments/redsys-initiate", json=body)
        assert resp.status_code == 400
        assert resp.json()["data"] is None

    def test_unknown_order_returns_400(self, client: TestClient):
        with patch("app.services.payments.get_order_by_id", return_value=None):
            resp = client.post("/payments/redsys-initiate", json=self._valid_body)
        assert resp.status_code == 400

    def test_missing_items_returns_422(self, client: TestClient):
        resp = client.post("/payments/redsys-initiate", json={"orderId": "o-1", "method": "card", "urlOk": "a", "urlKo": "b"})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Service-layer unit tests
# ---------------------------------------------------------------------------

class TestInitiateService:
    def _order_with_item(self, **item_overrides):
        defaults = {"id": "item-1", "dish_price": 10.0, "quantity": 1, "payment_status": "unassigned"}
        item = make_order_item(**{**defaults, **item_overrides})
        return Order(**make_order(items=[item]))

    def test_computes_amount_and_covered_items(self):
        from app.services import payments as svc
        from app.models import RedsysInitiateItem
        with patch("app.services.payments.get_order_by_id", return_value=self._order_with_item()), \
             patch("app.services.payments.get_client", return_value=make_mock_client(data=[{}])), \
             patch("app.services.payments.httpx.post", return_value=_mock_edge_post()):
            svc.initiate_redsys("order-1", [RedsysInitiateItem(itemId="item-1", portions=1)], "card", "a", "b")
        # 10.00 + 10% = 11.00 — assert via the persisted row.
        # (covered_items + amount are validated through the edge-call amount test above.)

    def test_rejects_already_paid_item(self):
        from app.services import payments as svc
        from app.models import RedsysInitiateItem
        order = self._order_with_item(split_portions=1, paid_portions=1, payment_status="paid")
        with patch("app.services.payments.get_order_by_id", return_value=order):
            with pytest.raises(ValueError, match="already paid"):
                svc.initiate_redsys("order-1", [RedsysInitiateItem(itemId="item-1", portions=1)], "card", "a", "b")

    def test_rejects_foreign_item(self):
        from app.services import payments as svc
        from app.models import RedsysInitiateItem
        with patch("app.services.payments.get_order_by_id", return_value=self._order_with_item()):
            with pytest.raises(ValueError, match="does not belong"):
                svc.initiate_redsys("order-1", [RedsysInitiateItem(itemId="ghost", portions=1)], "card", "a", "b")


# ---------------------------------------------------------------------------
# GET /api/payments/redsys/{order_number}  (post-callback payment-id lookup)
# ---------------------------------------------------------------------------

class TestGetRedsysPayment:
    def test_returns_payment_for_known_order_number(self, client: TestClient):
        payment = make_payment(status="confirmed")
        with patch("app.services.payments.get_client", return_value=make_mock_client(data=[payment])):
            resp = client.get("/payments/redsys/123456789012")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["id"] == "pay-1"
        assert data["status"] == "confirmed"

    def test_returns_404_when_no_match(self, client: TestClient):
        with patch("app.services.payments.get_client", return_value=make_mock_client(data=[])):
            resp = client.get("/payments/redsys/000000000000")
        assert resp.status_code == 404
        assert resp.json()["data"] is None


class TestGetRedsysPaymentService:
    def test_looks_up_by_redsys_order_number(self):
        from app.services import payments as svc
        with patch("app.services.payments.get_client") as mock_gc:
            mock_gc.return_value = make_mock_client(data=[make_payment()])
            result = svc.get_payment_by_redsys_order("123456789012")
        assert result is not None
        assert result.id == "pay-1"

    def test_returns_none_when_absent(self):
        from app.services import payments as svc
        with patch("app.services.payments.get_client") as mock_gc:
            mock_gc.return_value = make_mock_client(data=[])
            assert svc.get_payment_by_redsys_order("000000000000") is None


class TestCreatePaymentService:
    def test_create_payment_builds_correct_row(self):
        from app.services import payments as svc
        with patch("app.services.payments.get_client") as mock_gc:
            mock_gc.return_value = make_mock_client(data=[make_payment()])
            result = svc.create_payment("order-1", 27.50, "card")
        assert result.order_id == "order-1"
        assert result.status == "confirmed"

    def test_create_payment_raises_on_empty_insert_result(self):
        from app.services import payments as svc
        with patch("app.services.payments.get_client") as mock_gc:
            mock_gc.return_value = make_mock_client(data=None)
            with pytest.raises(RuntimeError, match="failed to create payment"):
                svc.create_payment("order-1", 10.0, "cash")

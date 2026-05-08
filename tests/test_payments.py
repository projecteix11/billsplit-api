"""
Tests for:
  POST /api/payments               – create payment (rate limited)
  POST /api/payments/redsys-sign   – generate Redsys payment signature (rate limited)
"""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from tests.conftest import make_payment, make_mock_client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_edge_response(amount_cents="5000", order_number="123456789012"):
    import base64, json
    params = {
        "DS_MERCHANT_AMOUNT": amount_cents,
        "DS_MERCHANT_ORDER": order_number,
        "DS_MERCHANT_MERCHANTCODE": "999008881",
        "DS_MERCHANT_TERMINAL": "001",
        "DS_MERCHANT_TRANSACTIONTYPE": "0",
        "DS_MERCHANT_CURRENCY": "978",
        "DS_MERCHANT_URLOK": "https://example.com/ok",
        "DS_MERCHANT_URLKO": "https://example.com/ko",
    }
    return {
        "Ds_MerchantParameters": base64.b64encode(json.dumps(params).encode()).decode(),
        "Ds_Signature": "dGVzdHNpZ25hdHVyZQ==",
        "Ds_SignatureVersion": "HMAC_SHA256_V1",
        "redsysUrl": "https://sis-t.redsys.es:25443/sis/realizarPago",
        "orderNumber": order_number,
    }


def _mock_requests_post(amount_cents="5000", order_number="123456789012"):
    mock_resp = MagicMock()
    mock_resp.json.return_value = _make_edge_response(amount_cents, order_number)
    mock_resp.raise_for_status.return_value = None
    return mock_resp


# ---------------------------------------------------------------------------
# POST /api/payments
# ---------------------------------------------------------------------------

class TestCreatePayment:
    _valid_body = {
        "orderId": "order-1",
        "amount": 27.50,
        "method": "card",
    }

    def test_create_payment_returns_201_on_success(self, client: TestClient):
        payment = make_payment()
        with patch("app.services.payments.get_client") as mock_gc:
            mock_gc.return_value = make_mock_client(data=[payment])
            resp = client.post("/payments", json=self._valid_body)

        assert resp.status_code == 201

    def test_create_payment_returns_data_envelope(self, client: TestClient):
        payment = make_payment()
        with patch("app.services.payments.get_client") as mock_gc:
            mock_gc.return_value = make_mock_client(data=[payment])
            resp = client.post("/payments", json=self._valid_body)

        body = resp.json()
        assert "data" in body
        assert body["error"] is None

    def test_create_payment_returns_correct_payment_fields(self, client: TestClient):
        payment = make_payment()
        with patch("app.services.payments.get_client") as mock_gc:
            mock_gc.return_value = make_mock_client(data=[payment])
            resp = client.post("/payments", json=self._valid_body)

        data = resp.json()["data"]
        assert data["id"] == "pay-1"
        assert data["order_id"] == "order-1"
        assert data["amount"] == 27.50
        assert data["tip_amount"] == 0.0
        assert data["total_charged"] == 27.50
        assert data["payment_method"] == "card"
        assert data["status"] == "confirmed"

    def test_create_payment_missing_order_id_returns_422(self, client: TestClient):
        resp = client.post("/payments", json={"amount": 10.0, "method": "cash"})
        assert resp.status_code == 422

    def test_create_payment_missing_amount_returns_422(self, client: TestClient):
        resp = client.post("/payments", json={"orderId": "o-1", "method": "cash"})
        assert resp.status_code == 422

    def test_create_payment_missing_method_returns_422(self, client: TestClient):
        resp = client.post("/payments", json={"orderId": "o-1", "amount": 10.0})
        assert resp.status_code == 422

    def test_create_payment_zero_amount_returns_400(self, client: TestClient):
        resp = client.post(
            "/payments",
            json={"orderId": "o-1", "amount": 0, "method": "cash"},
        )
        assert resp.status_code == 400
        body = resp.json()
        assert body["data"] is None

    def test_create_payment_empty_order_id_returns_400(self, client: TestClient):
        resp = client.post(
            "/payments",
            json={"orderId": "", "amount": 10.0, "method": "cash"},
        )
        assert resp.status_code == 400
        body = resp.json()
        assert body["data"] is None
        assert body["error"] is not None

    def test_create_payment_returns_500_on_db_error(self, client: TestClient):
        mock_q = make_mock_client()
        mock_q.execute.side_effect = RuntimeError("supabase 500: error")
        with patch("app.services.payments.get_client") as mock_gc:
            mock_gc.return_value = mock_q
            resp = client.post("/payments", json=self._valid_body)

        assert resp.status_code == 500
        body = resp.json()
        assert body["data"] is None
        assert body["error"] is not None

    def test_create_payment_returns_500_when_insert_returns_nothing(self, client: TestClient):
        with patch("app.services.payments.get_client") as mock_gc:
            mock_gc.return_value = make_mock_client(data=None)
            resp = client.post("/payments", json=self._valid_body)

        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# POST /api/payments/redsys-sign
# ---------------------------------------------------------------------------

class TestRedsysSign:
    _valid_body = {
        "amount": 50.00,
        "urlOk": "https://example.com/ok",
        "urlKo": "https://example.com/ko",
    }

    def test_redsys_sign_returns_200(self, client: TestClient):
        with patch("app.services.payments.httpx.post", return_value=_mock_requests_post()):
            resp = client.post("/payments/redsys-sign", json=self._valid_body)
        assert resp.status_code == 200

    def test_redsys_sign_returns_required_fields(self, client: TestClient):
        with patch("app.services.payments.httpx.post", return_value=_mock_requests_post()):
            resp = client.post("/payments/redsys-sign", json=self._valid_body)
        body = resp.json()
        assert "Ds_MerchantParameters" in body
        assert "Ds_Signature" in body
        assert "Ds_SignatureVersion" in body
        assert "redsysUrl" in body
        assert "orderNumber" in body

    def test_redsys_sign_signature_version_is_hmac_sha256(self, client: TestClient):
        with patch("app.services.payments.httpx.post", return_value=_mock_requests_post()):
            resp = client.post("/payments/redsys-sign", json=self._valid_body)
        assert resp.json()["Ds_SignatureVersion"] == "HMAC_SHA256_V1"

    def test_redsys_sign_order_number_max_12_chars(self, client: TestClient):
        with patch("app.services.payments.httpx.post", return_value=_mock_requests_post()):
            resp = client.post("/payments/redsys-sign", json=self._valid_body)
        assert len(resp.json()["orderNumber"]) <= 12

    def test_redsys_sign_redsys_url_is_present(self, client: TestClient):
        with patch("app.services.payments.httpx.post", return_value=_mock_requests_post()):
            resp = client.post("/payments/redsys-sign", json=self._valid_body)
        assert "redsys.es" in resp.json()["redsysUrl"]

    def test_redsys_sign_missing_amount_returns_422(self, client: TestClient):
        resp = client.post(
            "/payments/redsys-sign",
            json={"urlOk": "https://ok", "urlKo": "https://ko"},
        )
        assert resp.status_code == 422

    def test_redsys_sign_missing_url_ok_returns_422(self, client: TestClient):
        resp = client.post(
            "/payments/redsys-sign",
            json={"amount": 10.0, "urlKo": "https://ko"},
        )
        assert resp.status_code == 422

    def test_redsys_sign_missing_url_ko_returns_422(self, client: TestClient):
        resp = client.post(
            "/payments/redsys-sign",
            json={"amount": 10.0, "urlOk": "https://ok"},
        )
        assert resp.status_code == 422

    def test_redsys_sign_zero_amount_returns_400(self, client: TestClient):
        resp = client.post(
            "/payments/redsys-sign",
            json={"amount": 0, "urlOk": "https://ok", "urlKo": "https://ko"},
        )
        assert resp.status_code == 400
        assert resp.json()["data"] is None

    def test_redsys_sign_empty_url_ok_returns_400(self, client: TestClient):
        resp = client.post(
            "/payments/redsys-sign",
            json={"amount": 10.0, "urlOk": "", "urlKo": "https://ko"},
        )
        assert resp.status_code == 400

    def test_redsys_sign_empty_url_ko_returns_400(self, client: TestClient):
        resp = client.post(
            "/payments/redsys-sign",
            json={"amount": 10.0, "urlOk": "https://ok", "urlKo": ""},
        )
        assert resp.status_code == 400

    def test_redsys_sign_returns_500_when_edge_function_fails(self, client: TestClient):
        from httpx import HTTPStatusError
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = HTTPStatusError("502", request=MagicMock(), response=MagicMock())
        with patch("app.services.payments.httpx.post", return_value=mock_resp):
            resp = client.post("/payments/redsys-sign", json=self._valid_body)
        assert resp.status_code == 500
        assert resp.json()["data"] is None


# ---------------------------------------------------------------------------
# Pure unit tests for Redsys service (no HTTP layer)
# ---------------------------------------------------------------------------

class TestRedsysServiceUnit:
    def test_sign_redsys_calls_edge_function_with_correct_payload(self):
        from app.services.payments import sign_redsys
        mock_post = _mock_requests_post()
        with patch("app.services.payments.httpx.post", return_value=mock_post) as m:
            sign_redsys(50.0, "https://ok", "https://ko")
        call_args = m.call_args
        # httpx.post is called as httpx.post(url, json={...}, timeout=...)
        # args[1] or kwargs["json"]
        json_body = call_args.kwargs.get("json") or call_args[1].get("json")
        assert json_body["amount"] == 50.0
        assert json_body["urlOk"] == "https://ok"
        assert json_body["urlKo"] == "https://ko"

    def test_sign_redsys_returns_result_object(self):
        from app.services.payments import sign_redsys
        with patch("app.services.payments.httpx.post", return_value=_mock_requests_post()):
            result = sign_redsys(50.0, "https://ok", "https://ko")
        assert result.Ds_SignatureVersion == "HMAC_SHA256_V1"
        assert result.Ds_MerchantParameters
        assert result.Ds_Signature
        assert result.orderNumber

    def test_sign_redsys_dict_method_returns_all_keys(self):
        from app.services.payments import sign_redsys
        with patch("app.services.payments.httpx.post", return_value=_mock_requests_post()):
            result = sign_redsys(10.0, "https://ok", "https://ko")
        assert set(result.dict().keys()) == {
            "Ds_MerchantParameters",
            "Ds_Signature",
            "Ds_SignatureVersion",
            "redsysUrl",
            "orderNumber",
        }


# ---------------------------------------------------------------------------
# Pure unit tests for payment service (no HTTP layer)
# ---------------------------------------------------------------------------

class TestCreatePaymentService:
    def test_create_payment_builds_correct_row(self):
        from app.services import payments as svc
        payment_data = make_payment()

        with patch("app.services.payments.get_client") as mock_gc:
            mock_gc.return_value = make_mock_client(data=[payment_data])
            result = svc.create_payment("order-1", 27.50, "card")

        assert result.id == "pay-1"
        assert result.order_id == "order-1"
        assert result.status == "confirmed"

    def test_create_payment_raises_on_empty_insert_result(self):
        from app.services import payments as svc

        with patch("app.services.payments.get_client") as mock_gc:
            mock_gc.return_value = make_mock_client(data=None)
            with pytest.raises(RuntimeError, match="failed to create payment"):
                svc.create_payment("order-1", 10.0, "cash")

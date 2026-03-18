"""
Security tests for billsplit-api.

These tests verify the security posture of the API based on the security review findings.
Tests are organized by severity: Critical → High → Medium.

Many auth tests currently FAIL because the endpoints lack Depends(require_auth).
Those failures are intentional — they document missing fixes (C1, C3, C4).
"""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from tests.conftest import make_payment, make_order, make_order_item

# ---------------------------------------------------------------------------
# Auth header helper
# ---------------------------------------------------------------------------

VALID_TOKEN = "valid-bearer-token"
VALID_USER_ID = "user-uuid-123"

AUTH_HEADER = {"Authorization": f"Bearer {VALID_TOKEN}"}


def _mock_verify_token(token: str) -> str:
    if token == VALID_TOKEN:
        return VALID_USER_ID
    from fastapi import HTTPException
    raise HTTPException(status_code=401, detail="Invalid token")


# ===========================================================================
# CRITICAL — C1: POST /api/payments endpoints require auth
# ===========================================================================

class TestPaymentsRequireAuth:
    """C1 — POST /api/payments and POST /api/payments/redsys-sign must return 401
    without a valid Bearer token.

    CURRENT STATUS: These tests FAIL — endpoints lack Depends(require_auth).
    Fix: Add `_user_id: str = Depends(require_auth)` to both handlers.
    """

    def test_create_payment_without_token_returns_401(self, client: TestClient):
        resp = client.post(
            "/api/payments",
            json={"orderId": "order-1", "amount": 27.50, "method": "card"},
        )
        assert resp.status_code == 401, (
            f"Expected 401 Unauthorized but got {resp.status_code}. "
            "Fix: add Depends(require_auth) to create_payment handler."
        )

    def test_redsys_sign_without_token_returns_401(self, client: TestClient):
        resp = client.post(
            "/api/payments/redsys-sign",
            json={"amount": 10.0, "urlOk": "http://ok.test", "urlKo": "http://ko.test"},
        )
        assert resp.status_code == 401, (
            f"Expected 401 Unauthorized but got {resp.status_code}. "
            "Fix: add Depends(require_auth) to redsys_sign handler."
        )

    def test_create_payment_with_invalid_token_returns_401(self, client: TestClient):
        resp = client.post(
            "/api/payments",
            json={"orderId": "order-1", "amount": 27.50, "method": "card"},
            headers={"Authorization": "Bearer invalid-token"},
        )
        assert resp.status_code == 401


# ===========================================================================
# CRITICAL — C3: POST /api/orders/{id}/items and PATCH /api/orders/{id}/close
# ===========================================================================

class TestOrderMutationsRequireAuth:
    """C3 — Mutation endpoints on orders must require authentication.

    CURRENT STATUS: These tests FAIL — endpoints lack Depends(require_auth).
    Fix: Add `_user_id: str = Depends(require_auth)` to each handler.
    """

    _items_body = {
        "items": [
            {
                "dish_name": "Pizza",
                "dish_price": 12.50,
                "quantity": 1,
                "diner_name": "Ana",
            }
        ]
    }

    def test_add_items_to_order_without_token_returns_401(self, client: TestClient):
        resp = client.post("/api/orders/order-1/items", json=self._items_body)
        assert resp.status_code == 401, (
            f"Expected 401 Unauthorized but got {resp.status_code}. "
            "Fix: add Depends(require_auth) to add_items_to_order handler."
        )

    def test_close_order_without_token_returns_401(self, client: TestClient):
        resp = client.patch("/api/orders/order-1/close")
        assert resp.status_code == 401, (
            f"Expected 401 Unauthorized but got {resp.status_code}. "
            "Fix: add Depends(require_auth) to close_order handler."
        )

    def test_add_items_with_invalid_token_returns_401(self, client: TestClient):
        resp = client.post(
            "/api/orders/order-1/items",
            json=self._items_body,
            headers={"Authorization": "Bearer bad-token"},
        )
        assert resp.status_code == 401

    def test_close_order_with_invalid_token_returns_401(self, client: TestClient):
        resp = client.patch(
            "/api/orders/order-1/close",
            headers={"Authorization": "Bearer bad-token"},
        )
        assert resp.status_code == 401


# ===========================================================================
# CRITICAL — C4: PATCH /api/order-items/payment-status requires auth
# ===========================================================================

class TestPaymentStatusRequiresAuth:
    """C4 — PATCH /api/order-items/payment-status must require authentication.

    CURRENT STATUS: This test FAILS — endpoint lacks Depends(require_auth).
    Fix: Add `_user_id: str = Depends(require_auth)` to update_payment_status handler.
    """

    _body = {"itemIds": ["item-1", "item-2"], "status": "assigned"}

    def test_update_payment_status_without_token_returns_401(self, client: TestClient):
        resp = client.patch("/api/order-items/payment-status", json=self._body)
        assert resp.status_code == 401, (
            f"Expected 401 Unauthorized but got {resp.status_code}. "
            "Fix: add Depends(require_auth) to update_payment_status handler."
        )

    def test_update_payment_status_with_invalid_token_returns_401(self, client: TestClient):
        resp = client.patch(
            "/api/order-items/payment-status",
            json=self._body,
            headers={"Authorization": "Bearer bad-token"},
        )
        assert resp.status_code == 401


# ===========================================================================
# HIGH — H4: amount=0 and amount<0 must be rejected
# ===========================================================================

class TestPaymentAmountValidation:
    """H4 — `if not body.amount` evaluates True for 0.0, allowing zero-value payments.

    CURRENT STATUS: These tests FAIL — amount=0 currently passes validation.
    Fix: Use Pydantic Field(gt=0) on CreatePaymentBody.amount and RedsysSignBody.amount.
    """

    def test_create_payment_with_zero_amount_returns_422(self, client: TestClient):
        with patch("app.db.supabase.verify_token", return_value=VALID_USER_ID):
            resp = client.post(
                "/api/payments",
                json={"orderId": "order-1", "amount": 0.0, "method": "card"},
                headers=AUTH_HEADER,
            )
        assert resp.status_code == 422

    def test_create_payment_with_negative_amount_returns_422(self, client: TestClient):
        with patch("app.db.supabase.verify_token", return_value=VALID_USER_ID):
            resp = client.post(
                "/api/payments",
                json={"orderId": "order-1", "amount": -5.0, "method": "card"},
                headers=AUTH_HEADER,
            )
        assert resp.status_code == 422

    def test_redsys_sign_with_zero_amount_returns_422(self, client: TestClient):
        with patch("app.db.supabase.verify_token", return_value=VALID_USER_ID):
            resp = client.post(
                "/api/payments/redsys-sign",
                json={"amount": 0.0, "urlOk": "http://ok.test", "urlKo": "http://ko.test"},
                headers=AUTH_HEADER,
            )
        assert resp.status_code == 422

    def test_redsys_sign_with_negative_amount_returns_422(self, client: TestClient):
        with patch("app.db.supabase.verify_token", return_value=VALID_USER_ID):
            resp = client.post(
                "/api/payments/redsys-sign",
                json={"amount": -1.0, "urlOk": "http://ok.test", "urlKo": "http://ko.test"},
                headers=AUTH_HEADER,
            )
        assert resp.status_code == 422

    def test_create_payment_with_positive_amount_passes_validation(self, client: TestClient):
        with patch("app.db.supabase.verify_token", return_value=VALID_USER_ID):
            with patch("app.services.payments.supabase") as mock_sb:
                mock_sb.insert.return_value = [make_payment()]
                resp = client.post(
                    "/api/payments",
                    json={"orderId": "order-1", "amount": 0.01, "method": "card"},
                    headers=AUTH_HEADER,
                )
        assert resp.status_code == 201


# ===========================================================================
# MEDIUM — M1: NewOrderItem constraints
# ===========================================================================

class TestOrderItemModelValidation:
    """M1 — NewOrderItem should reject invalid prices, quantities, and names.

    CURRENT STATUS: Most of these tests FAIL — no Field constraints on NewOrderItem.
    Fix: Add Field(gt=0) on dish_price, Field(ge=1) on quantity.
    """

    _base_item = {
        "dish_name": "Pizza",
        "dish_price": 12.50,
        "quantity": 1,
        "diner_name": "Ana",
    }

    def _order_body(self, item_override: dict) -> dict:
        item = {**self._base_item, **item_override}
        return {"tableId": "table-1", "tableNumber": 5, "items": [item]}

    def _items_body(self, item_override: dict) -> dict:
        item = {**self._base_item, **item_override}
        return {"items": [item]}

    def test_create_order_with_zero_dish_price_returns_422(self, client: TestClient):
        resp = client.post("/api/orders", json=self._order_body({"dish_price": 0.0}))
        assert resp.status_code == 422, (
            f"dish_price=0 should be rejected. Got {resp.status_code}."
        )

    def test_create_order_with_negative_dish_price_returns_422(self, client: TestClient):
        resp = client.post("/api/orders", json=self._order_body({"dish_price": -1.0}))
        assert resp.status_code == 422

    def test_create_order_with_zero_quantity_returns_422(self, client: TestClient):
        resp = client.post("/api/orders", json=self._order_body({"quantity": 0}))
        assert resp.status_code == 422, (
            f"quantity=0 should be rejected. Got {resp.status_code}."
        )

    def test_create_order_with_negative_quantity_returns_422(self, client: TestClient):
        resp = client.post("/api/orders", json=self._order_body({"quantity": -1}))
        assert resp.status_code == 422

    def test_create_order_with_empty_dish_name_returns_422(self, client: TestClient):
        resp = client.post("/api/orders", json=self._order_body({"dish_name": ""}))
        assert resp.status_code == 422

    def test_create_order_with_valid_item_passes_model_validation(self, client: TestClient):
        """Valid items must pass Pydantic validation (may fail at DB level)."""
        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.insert.return_value = [make_order()]
            resp = client.post("/api/orders", json=self._order_body({}))
        assert resp.status_code != 422


# ===========================================================================
# MEDIUM — M6: itemIds list must have a maximum length
# ===========================================================================

class TestPaymentStatusListLimit:
    """M6 — itemIds list without a max length allows DoS via huge IN queries.

    CURRENT STATUS: This test FAILS — no max_length on itemIds field.
    Fix: Add Field(max_length=100) on PaymentStatusBody.itemIds.
    """

    def test_payment_status_with_101_item_ids_returns_422(self, client: TestClient):
        huge_list = [f"item-{i}" for i in range(101)]
        with patch("app.db.supabase.verify_token", return_value=VALID_USER_ID):
            resp = client.patch(
                "/api/order-items/payment-status",
                json={"itemIds": huge_list, "status": "assigned"},
                headers=AUTH_HEADER,
            )
        assert resp.status_code == 422

    def test_payment_status_with_100_item_ids_passes_validation(self, client: TestClient):
        """Exactly 100 items must be accepted."""
        max_list = [f"item-{i}" for i in range(100)]
        with patch("app.db.supabase.verify_token", return_value=VALID_USER_ID):
            with patch("app.services.orders.supabase") as mock_sb:
                mock_sb.update.return_value = []
                resp = client.patch(
                    "/api/order-items/payment-status",
                    json={"itemIds": max_list, "status": "assigned"},
                    headers=AUTH_HEADER,
                )
        assert resp.status_code == 200

    def test_payment_status_with_empty_list_is_handled(self, client: TestClient):
        """Empty list returns 400 (router guard) not a server crash."""
        with patch("app.db.supabase.verify_token", return_value=VALID_USER_ID):
            resp = client.patch(
                "/api/order-items/payment-status",
                json={"itemIds": [], "status": "assigned"},
                headers=AUTH_HEADER,
            )
        assert resp.status_code == 400


# ===========================================================================
# HIGH — H1: Error responses must not leak internal details
# ===========================================================================

class TestErrorResponseSafety:
    """H1 — HTTP 500 responses must not include Supabase error messages.

    CURRENT STATUS: This test FAILS — routers return str(e) directly in error field.
    Fix: Use a safe_error_response() wrapper that logs internally and returns generic message.
    """

    def test_db_error_does_not_expose_internal_message(self, client: TestClient):
        internal_msg = "supabase 403: permission denied for table orders"
        with patch("app.db.supabase.verify_token", return_value=VALID_USER_ID):
            with patch("app.services.orders.supabase") as mock_sb:
                mock_sb.select.side_effect = Exception(internal_msg)
                resp = client.get("/api/orders", headers=AUTH_HEADER)

        assert resp.status_code == 500
        body = resp.json()
        error_str = str(body.get("error", ""))
        assert "supabase" not in error_str.lower(), (
            f"Internal Supabase error message leaked: {error_str!r}"
        )
        assert "permission denied" not in error_str.lower(), (
            f"DB permission error leaked: {error_str!r}"
        )

    def test_db_error_returns_generic_message(self, client: TestClient):
        with patch("app.db.supabase.verify_token", return_value=VALID_USER_ID):
            with patch("app.services.orders.supabase") as mock_sb:
                mock_sb.select.side_effect = Exception("internal db crash")
                resp = client.get("/api/orders", headers=AUTH_HEADER)

        assert resp.status_code == 500
        body = resp.json()
        # Error message should be user-facing, not a raw exception dump
        assert body.get("error") is not None
        assert body.get("data") is None

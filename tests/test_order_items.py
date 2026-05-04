"""
Tests for:
  PATCH /api/order-items/{item_id}/kitchen-status  (AUTH REQUIRED, rate limited)
  PATCH /api/order-items/payment-status             (no auth, rate limited)

Auth is checked via require_auth dependency → supabase.verify_token.
"""

import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from tests.conftest import VALID_TOKEN, VALID_USER_ID, VALID_TENANT_ID


def _auth_headers(token: str = VALID_TOKEN) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# PATCH /api/order-items/{item_id}/kitchen-status
# ---------------------------------------------------------------------------

class TestUpdateKitchenStatus:
    _valid_body = {"status": "cooking"}

    def test_update_kitchen_status_returns_200_with_valid_auth(self, client: TestClient):
        with patch("app.db.supabase.verify_token_full", return_value=(VALID_USER_ID, VALID_TENANT_ID, "developer")):
            with patch("app.services.orders.supabase") as mock_sb:
                mock_sb.update.return_value = None
                resp = client.patch(
                    "/order-items/item-1/kitchen-status",
                    json=self._valid_body,
                    headers=_auth_headers(),
                )

        assert resp.status_code == 200

    def test_update_kitchen_status_returns_null_data_envelope(self, client: TestClient):
        with patch("app.db.supabase.verify_token_full", return_value=(VALID_USER_ID, VALID_TENANT_ID, "developer")):
            with patch("app.services.orders.supabase") as mock_sb:
                mock_sb.update.return_value = None
                resp = client.patch(
                    "/order-items/item-1/kitchen-status",
                    json=self._valid_body,
                    headers=_auth_headers(),
                )

        assert resp.json() == {"data": None, "error": None}

    def test_update_kitchen_status_requires_auth_without_token(self, client: TestClient):
        resp = client.patch(
            "/order-items/item-1/kitchen-status",
            json=self._valid_body,
        )
        assert resp.status_code == 401

    def test_update_kitchen_status_requires_auth_with_bad_token(self, client: TestClient):
        with patch("app.middleware.auth.supabase.verify_token_full", side_effect=ValueError("bad token")):
            resp = client.patch(
                "/order-items/item-1/kitchen-status",
                json=self._valid_body,
                headers=_auth_headers("bad-token"),
            )
        assert resp.status_code == 401

    def test_update_kitchen_status_requires_auth_malformed_header(self, client: TestClient):
        resp = client.patch(
            "/order-items/item-1/kitchen-status",
            json=self._valid_body,
            headers={"Authorization": "Token abc"},
        )
        assert resp.status_code == 401

    @pytest.mark.parametrize("status", ["pending", "cooking", "ready", "delivered"])
    def test_update_kitchen_status_accepts_all_valid_statuses(self, client: TestClient, status: str):
        with patch("app.db.supabase.verify_token_full", return_value=(VALID_USER_ID, VALID_TENANT_ID, "developer")):
            with patch("app.services.orders.supabase") as mock_sb:
                mock_sb.update.return_value = None
                resp = client.patch(
                    "/order-items/item-1/kitchen-status",
                    json={"status": status},
                    headers=_auth_headers(),
                )
        assert resp.status_code == 200

    @pytest.mark.parametrize("bad_status", ["done", "", "COOKING", "unknown"])
    def test_update_kitchen_status_rejects_invalid_status(self, client: TestClient, bad_status: str):
        with patch("app.db.supabase.verify_token_full", return_value=(VALID_USER_ID, VALID_TENANT_ID, "developer")):
            resp = client.patch(
                "/order-items/item-1/kitchen-status",
                json={"status": bad_status},
                headers=_auth_headers(),
            )
        assert resp.status_code == 400
        body = resp.json()
        assert body["data"] is None
        assert "cancelled" in body["error"]

    def test_update_kitchen_status_missing_status_field_returns_422(self, client: TestClient):
        with patch("app.db.supabase.verify_token_full", return_value=(VALID_USER_ID, VALID_TENANT_ID, "developer")):
            resp = client.patch(
                "/order-items/item-1/kitchen-status",
                json={},
                headers=_auth_headers(),
            )
        assert resp.status_code == 422

    def test_update_kitchen_status_calls_update_correct_item(self, client: TestClient):
        with patch("app.db.supabase.verify_token_full", return_value=(VALID_USER_ID, VALID_TENANT_ID, "developer")):
            with patch("app.services.orders.supabase") as mock_sb:
                mock_sb.update.return_value = None
                client.patch(
                    "/order-items/my-item-uuid/kitchen-status",
                    json={"status": "ready"},
                    headers=_auth_headers(),
                )

        call_args = mock_sb.update.call_args
        assert call_args[0][0] == "order_items"
        assert "my-item-uuid" in call_args[0][1]
        assert call_args[0][2]["kitchen_status"] == "ready"

    def test_update_kitchen_status_returns_500_on_db_error(self, client: TestClient):
        with patch("app.db.supabase.verify_token_full", return_value=(VALID_USER_ID, VALID_TENANT_ID, "developer")):
            with patch("app.services.orders.supabase") as mock_sb:
                mock_sb.update.side_effect = RuntimeError("db failure")
                resp = client.patch(
                    "/order-items/item-1/kitchen-status",
                    json=self._valid_body,
                    headers=_auth_headers(),
                )

        assert resp.status_code == 500
        assert resp.json()["data"] is None


# ---------------------------------------------------------------------------
# PATCH /api/order-items/payment-status
# ---------------------------------------------------------------------------

class TestUpdatePaymentStatus:
    _valid_body = {"itemIds": ["item-1", "item-2"], "status": "paid"}

    def test_update_payment_status_returns_200(self, client: TestClient):
        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.update.return_value = None
            mock_sb.select.return_value = []  # auto_close_if_complete returns early
            resp = client.patch("/order-items/payment-status", json=self._valid_body)

        assert resp.status_code == 200

    def test_update_payment_status_returns_null_data_envelope(self, client: TestClient):
        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.update.return_value = None
            mock_sb.select.return_value = []
            resp = client.patch("/order-items/payment-status", json=self._valid_body)

        assert resp.json() == {"data": None, "error": None}

    @pytest.mark.parametrize("status", ["unassigned", "assigned", "paid"])
    def test_update_payment_status_accepts_all_valid_statuses(self, client: TestClient, status: str):
        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.update.return_value = None
            mock_sb.select.return_value = []
            resp = client.patch(
                "/order-items/payment-status",
                json={"itemIds": ["item-1"], "status": status},
            )
        assert resp.status_code == 200

    @pytest.mark.parametrize("bad_status", ["done", "refunded", "", "PAID", "pending"])
    def test_update_payment_status_rejects_invalid_status(self, client: TestClient, bad_status: str):
        resp = client.patch(
            "/order-items/payment-status",
            json={"itemIds": ["item-1"], "status": bad_status},
        )
        assert resp.status_code == 400
        body = resp.json()
        assert body["data"] is None
        assert "unassigned, assigned, paid" in body["error"]

    def test_update_payment_status_empty_item_ids_returns_400(self, client: TestClient):
        resp = client.patch(
            "/order-items/payment-status",
            json={"itemIds": [], "status": "paid"},
        )
        assert resp.status_code == 400
        body = resp.json()
        assert body["data"] is None
        assert "itemIds[]" in body["error"]

    def test_update_payment_status_missing_item_ids_returns_422(self, client: TestClient):
        resp = client.patch(
            "/order-items/payment-status",
            json={"status": "paid"},
        )
        assert resp.status_code == 422

    def test_update_payment_status_missing_status_returns_422(self, client: TestClient):
        resp = client.patch(
            "/order-items/payment-status",
            json={"itemIds": ["item-1"]},
        )
        assert resp.status_code == 422

    def test_update_payment_status_calls_update_with_in_clause(self, client: TestClient):
        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.update.return_value = None
            client.patch(
                "/order-items/payment-status",
                json={"itemIds": ["item-a", "item-b"], "status": "assigned"},
            )

        call_args = mock_sb.update.call_args
        assert call_args[0][0] == "order_items"
        query = call_args[0][1]
        assert "item-a" in query
        assert "item-b" in query
        assert call_args[0][2]["payment_status"] == "assigned"

    def test_update_payment_status_does_not_require_auth(self, client: TestClient):
        """Payment-status endpoint has no auth requirement."""
        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.update.return_value = None
            mock_sb.select.return_value = []
            resp = client.patch("/order-items/payment-status", json=self._valid_body)
        # No Authorization header, must still succeed
        assert resp.status_code == 200

    def test_update_payment_status_returns_500_on_db_error(self, client: TestClient):
        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.update.side_effect = RuntimeError("update error")
            resp = client.patch("/order-items/payment-status", json=self._valid_body)

        assert resp.status_code == 500
        assert resp.json()["data"] is None

    def test_update_payment_status_single_item(self, client: TestClient):
        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.update.return_value = None
            mock_sb.select.return_value = []
            resp = client.patch(
                "/order-items/payment-status",
                json={"itemIds": ["single-item-id"], "status": "paid"},
            )
        assert resp.status_code == 200

    def test_auto_close_triggered_when_all_items_paid(self, client: TestClient):
        from tests.conftest import make_order, make_order_item
        item = make_order_item(payment_status="paid", kitchen_status="delivered")
        order = make_order(items=[item])
        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.update.return_value = None
            # auto_close_if_complete: select order_id from order_items
            # get_order_by_id (inside auto_close_if_complete): select order + items
            # get_order_by_id (inside close_order): select order + items
            mock_sb.select.side_effect = [
                [{"order_id": "order-1"}],  # auto_close: find order_id
                [order],                     # auto_close: get_order_by_id
                [order],                     # close_order: get_order_by_id
            ]
            with patch("app.services.dishes.supabase") as mock_dish_sb:
                mock_dish_sb.delete.return_value = None
                client.patch("/order-items/payment-status", json={"itemIds": ["item-1"], "status": "paid"})

        tables_updated = [
            c for c in mock_sb.update.call_args_list
            if c[0][0] == "restaurant_tables"
        ]
        assert len(tables_updated) == 1
        assert tables_updated[0][0][2]["status"] == "available"

    def test_auto_close_not_triggered_for_non_paid_status(self, client: TestClient):
        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.update.return_value = None
            client.patch("/order-items/payment-status", json={"itemIds": ["item-1"], "status": "assigned"})

        # select should never be called — auto_close only fires on paid
        mock_sb.select.assert_not_called()

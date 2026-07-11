"""
Tests for:
  PATCH /api/order-items/{item_id}/kitchen-status  (AUTH REQUIRED, rate limited)
  PATCH /api/order-items/payment-status             (no auth, rate limited)
  DELETE /api/order-items/{item_id}
  PATCH /api/order-items/{item_id}/quantity
  PATCH /api/order-items/{item_id}/price
"""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from tests.conftest import (
    make_mock_client, make_order, make_order_item,
    VALID_TOKEN, VALID_USER_ID, VALID_TENANT_ID,
)


def _auth_headers(token: str = VALID_TOKEN) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _owner_row():
    return [{"order_id": "order-1", "order": {"tenant_id": VALID_TENANT_ID}}]


# ---------------------------------------------------------------------------
# PATCH /api/order-items/{item_id}/kitchen-status
# ---------------------------------------------------------------------------

class TestUpdateKitchenStatus:
    _valid_body = {"status": "cooking"}

    def test_update_kitchen_status_returns_200_with_valid_auth(self, client: TestClient):
        mock_q = make_mock_client()
        mock_q.execute.side_effect = [
            MagicMock(data=_owner_row()),  # _assert_item_owner
        ] + [MagicMock(data=None)] * 10  # update + _sync get_order_by_id (None -> no-op)
        with patch("app.db.supabase.verify_token_full", return_value=(VALID_USER_ID, VALID_TENANT_ID, "developer")):
            with patch("app.services.orders.get_client") as mock_gc:
                mock_gc.return_value = mock_q
                resp = client.patch(
                    "/order-items/item-1/kitchen-status",
                    json=self._valid_body,
                    headers=_auth_headers(),
                )

        assert resp.status_code == 200

    def test_update_kitchen_status_returns_null_data_envelope(self, client: TestClient):
        mock_q = make_mock_client()
        mock_q.execute.side_effect = [
            MagicMock(data=_owner_row()),  # _assert_item_owner
        ] + [MagicMock(data=None)] * 10  # update + _sync get_order_by_id (None -> no-op)
        with patch("app.db.supabase.verify_token_full", return_value=(VALID_USER_ID, VALID_TENANT_ID, "developer")):
            with patch("app.services.orders.get_client") as mock_gc:
                mock_gc.return_value = mock_q
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
        with patch("app.db.supabase.verify_token_full", side_effect=ValueError("bad token")):
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
        mock_q = make_mock_client()
        mock_q.execute.side_effect = [
            MagicMock(data=_owner_row()),  # _assert_item_owner
        ] + [MagicMock(data=None)] * 10  # update + _sync get_order_by_id (None -> no-op)
        with patch("app.db.supabase.verify_token_full", return_value=(VALID_USER_ID, VALID_TENANT_ID, "developer")):
            with patch("app.services.orders.get_client") as mock_gc:
                mock_gc.return_value = mock_q
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

    def test_update_kitchen_status_returns_404_for_wrong_tenant(self, client: TestClient):
        with patch("app.db.supabase.verify_token_full", return_value=(VALID_USER_ID, VALID_TENANT_ID, "developer")):
            with patch("app.services.orders.get_client") as mock_gc:
                mock_gc.return_value = make_mock_client(
                    data=[{"order_id": "order-1", "order": {"tenant_id": "other-tenant"}}]
                )
                resp = client.patch(
                    "/order-items/item-1/kitchen-status",
                    json=self._valid_body,
                    headers=_auth_headers(),
                )
        assert resp.status_code == 404

    def test_update_kitchen_status_returns_404_when_item_not_found(self, client: TestClient):
        with patch("app.db.supabase.verify_token_full", return_value=(VALID_USER_ID, VALID_TENANT_ID, "developer")):
            with patch("app.services.orders.get_client") as mock_gc:
                mock_gc.return_value = make_mock_client(data=[])
                resp = client.patch(
                    "/order-items/nonexistent/kitchen-status",
                    json=self._valid_body,
                    headers=_auth_headers(),
                )
        assert resp.status_code == 404

    def test_update_kitchen_status_returns_500_on_db_error(self, client: TestClient):
        mock_q = make_mock_client()
        mock_q.execute.side_effect = [
            MagicMock(data=_owner_row()),
            RuntimeError("db failure"),
        ]
        with patch("app.db.supabase.verify_token_full", return_value=(VALID_USER_ID, VALID_TENANT_ID, "developer")):
            with patch("app.services.orders.get_client") as mock_gc:
                mock_gc.return_value = mock_q
                resp = client.patch(
                    "/order-items/item-1/kitchen-status",
                    json=self._valid_body,
                    headers=_auth_headers(),
                )

        assert resp.status_code == 500
        assert resp.json()["data"] is None

    def test_update_kitchen_status_waiter_blocks_invalid_status_or_source(self, client: TestClient):
        # Current status is 'cooking' (waiter cannot transition from cooking)
        with patch("app.db.supabase.verify_token_full", return_value=(VALID_USER_ID, VALID_TENANT_ID, "waiter")):
            with patch("app.routers.order_items.activity_svc.get_order_item_context", return_value={"kitchen_status": "cooking"}):
                resp = client.patch(
                    "/order-items/item-1/kitchen-status",
                    json={"status": "delivered"},
                    headers=_auth_headers(),
                )
        assert resp.status_code == 403
        assert "Waiters can only" in resp.json()["error"]

    def test_update_kitchen_status_waiter_allows_delivered_when_ready(self, client: TestClient):
        # Current status is 'ready', target is 'delivered'
        mock_q = make_mock_client()
        mock_q.execute.side_effect = [
            MagicMock(data=_owner_row()),  # _assert_item_owner
        ] + [MagicMock(data=None)] * 10
        with patch("app.db.supabase.verify_token_full", return_value=(VALID_USER_ID, VALID_TENANT_ID, "waiter")):
            with patch("app.routers.order_items.activity_svc.get_order_item_context", return_value={"kitchen_status": "ready"}):
                with patch("app.services.orders.get_client", return_value=mock_q):
                    resp = client.patch(
                        "/order-items/item-1/kitchen-status",
                        json={"status": "delivered"},
                        headers=_auth_headers(),
                    )
        assert resp.status_code == 200

    def test_update_kitchen_status_kitchen_blocks_delivered_or_cancelled(self, client: TestClient):
        # Kitchen cannot set to 'delivered'
        with patch("app.db.supabase.verify_token_full", return_value=(VALID_USER_ID, VALID_TENANT_ID, "kitchen")):
            with patch("app.routers.order_items.activity_svc.get_order_item_context", return_value={"kitchen_status": "cooking"}):
                resp = client.patch(
                    "/order-items/item-1/kitchen-status",
                    json={"status": "delivered"},
                    headers=_auth_headers(),
                )
        assert resp.status_code == 403
        assert "Kitchen staff can only" in resp.json()["error"]

    def test_update_kitchen_status_kitchen_blocks_modifying_delivered_or_cancelled(self, client: TestClient):
        # Current status is 'delivered', kitchen attempts to set back to 'ready'
        with patch("app.db.supabase.verify_token_full", return_value=(VALID_USER_ID, VALID_TENANT_ID, "kitchen")):
            with patch("app.routers.order_items.activity_svc.get_order_item_context", return_value={"kitchen_status": "delivered"}):
                resp = client.patch(
                    "/order-items/item-1/kitchen-status",
                    json={"status": "ready"},
                    headers=_auth_headers(),
                )
        assert resp.status_code == 403
        assert "Kitchen staff cannot modify items that are already" in resp.json()["error"]

    def test_update_kitchen_status_triggers_notification_when_enabled(self, client: TestClient):
        mock_q = make_mock_client()
        mock_q.execute.side_effect = [
            MagicMock(data=_owner_row()),  # 1. _assert_item_owner
            MagicMock(data=None),          # 2. update order_items
            MagicMock(data=None),          # 3. get_order_by_id in _sync
            MagicMock(data=[{"features": {"waiter_ready_notifications": True}}]),  # 4. select features
        ] + [MagicMock(data=None)] * 10
        with patch("app.db.supabase.verify_token_full", return_value=(VALID_USER_ID, VALID_TENANT_ID, "developer")):
            with patch("app.routers.order_items.activity_svc.get_order_item_context", return_value={"kitchen_status": "cooking", "dish_name": "Pizza", "order": {"table_number": 5}}):
                with patch("app.services.orders.get_client", return_value=mock_q):
                    with patch("app.db.supabase.get_client", return_value=mock_q):
                        with patch("app.services.notifications.broadcast_notification") as mock_broadcast:
                            resp = client.patch(
                                "/order-items/item-1/kitchen-status",
                                json={"status": "ready"},
                                headers=_auth_headers(),
                            )
                            assert resp.status_code == 200
                            mock_broadcast.assert_called_once_with(
                                tenant_id=VALID_TENANT_ID,
                                title="notifications.dish_ready_title",
                                description="notifications.dish_ready_desc",
                                notification_type="order_ready",
                                params={"dish": "Pizza", "table": "5", "item_id": "item-1"},
                            )

    def test_update_kitchen_status_does_not_trigger_when_disabled(self, client: TestClient):
        mock_q = make_mock_client()
        mock_q.execute.side_effect = [
            MagicMock(data=_owner_row()),  # 1. _assert_item_owner
            MagicMock(data=None),          # 2. update order_items
            MagicMock(data=None),          # 3. get_order_by_id in _sync
            MagicMock(data=[{"features": {"waiter_ready_notifications": False}}]),  # 4. select features
        ] + [MagicMock(data=None)] * 10
        with patch("app.db.supabase.verify_token_full", return_value=(VALID_USER_ID, VALID_TENANT_ID, "developer")):
            with patch("app.routers.order_items.activity_svc.get_order_item_context", return_value={"kitchen_status": "cooking", "dish_name": "Pizza", "order": {"table_number": 5}}):
                with patch("app.services.orders.get_client", return_value=mock_q):
                    with patch("app.db.supabase.get_client", return_value=mock_q):
                        with patch("app.services.notifications.broadcast_notification") as mock_broadcast:
                            resp = client.patch(
                                "/order-items/item-1/kitchen-status",
                                json={"status": "ready"},
                                headers=_auth_headers(),
                            )
                            assert resp.status_code == 200
                            mock_broadcast.assert_not_called()




# ---------------------------------------------------------------------------
# PATCH /api/order-items/payment-status
# ---------------------------------------------------------------------------

class TestUpdatePaymentStatus:
    _valid_body = {"itemIds": ["item-1", "item-2"], "status": "paid"}

    @pytest.fixture(autouse=True)
    def _staff_auth(self, app):
        """payment-status and payment-portions are staff-only now (XC-1): satisfy
        require_auth for this class so the behavioural tests below still exercise
        the handler. The unauthenticated-rejection case is covered in test_auth.py."""
        from app.middleware.auth import require_auth
        app.dependency_overrides[require_auth] = lambda: VALID_USER_ID
        yield
        app.dependency_overrides.pop(require_auth, None)

    @staticmethod
    def _ownership_rows(*item_ids: str) -> list:
        return [{"id": iid, "order": {"tenant_id": VALID_TENANT_ID}} for iid in item_ids]

    def test_update_payment_status_returns_200(self, client: TestClient):
        mock_q = make_mock_client()
        mock_q.execute.side_effect = [
            MagicMock(data=self._ownership_rows("item-1", "item-2")),
            MagicMock(data=None),  # update
            MagicMock(data=[]),    # auto_close: batch order_ids (no items → skip)
        ]
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = mock_q
            resp = client.patch("/order-items/payment-status", json=self._valid_body)

        assert resp.status_code == 200

    def test_update_payment_status_returns_null_data_envelope(self, client: TestClient):
        mock_q = make_mock_client()
        mock_q.execute.side_effect = [
            MagicMock(data=self._ownership_rows("item-1", "item-2")),
            MagicMock(data=None),
            MagicMock(data=[]),
        ]
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = mock_q
            resp = client.patch("/order-items/payment-status", json=self._valid_body)

        assert resp.json() == {"data": None, "error": None}

    @pytest.mark.parametrize("status", ["unassigned", "assigned", "paid"])
    def test_update_payment_status_accepts_all_valid_statuses(self, client: TestClient, status: str):
        mock_q = make_mock_client()
        if status == "paid":
            mock_q.execute.side_effect = [
                MagicMock(data=self._ownership_rows("item-1")),
                MagicMock(data=None),
                MagicMock(data=[]),
            ]
        else:
            mock_q.execute.side_effect = [
                MagicMock(data=self._ownership_rows("item-1")),
                MagicMock(data=None),
            ]
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = mock_q
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

    def test_update_payment_status_does_not_require_auth(self, client: TestClient):
        mock_q = make_mock_client()
        mock_q.execute.side_effect = [
            MagicMock(data=self._ownership_rows("item-1", "item-2")),
            MagicMock(data=None),
            MagicMock(data=[]),
        ]
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = mock_q
            resp = client.patch("/order-items/payment-status", json=self._valid_body)
        assert resp.status_code == 200

    def test_update_payment_status_returns_500_on_db_error(self, client: TestClient):
        mock_q = make_mock_client()
        mock_q.execute.side_effect = [
            MagicMock(data=self._ownership_rows("item-1", "item-2")),
            RuntimeError("update error"),
        ]
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = mock_q
            resp = client.patch("/order-items/payment-status", json=self._valid_body)

        assert resp.status_code == 500
        assert resp.json()["data"] is None

    def test_payment_status_returns_404_when_item_not_found(self, client: TestClient):
        # Only 1 of 2 items found
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = make_mock_client(
                data=self._ownership_rows("item-1")
            )
            resp = client.patch(
                "/order-items/payment-status",
                json={"itemIds": ["item-1", "missing-id"], "status": "assigned"},
            )

        assert resp.status_code == 404

    def test_auto_close_triggered_when_all_items_paid(self, client: TestClient):
        item = make_order_item(payment_status="paid", kitchen_status="delivered")
        order = make_order(items=[item])
        mock_q = make_mock_client()
        mock_q.execute.side_effect = [
            MagicMock(data=[{"id": "item-1", "order": {"tenant_id": VALID_TENANT_ID}}]),
            MagicMock(data=None),               # update payment_status
            MagicMock(data=[{"order_id": "order-1"}]),  # auto_close batch
            MagicMock(data=[order]),             # _maybe_close_order: get_order_by_id
            MagicMock(data=[order]),             # close_order: get_order_by_id
            MagicMock(data=None),                # orders update
            MagicMock(data=None),                # restaurant_tables update
        ]
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = mock_q
            with patch("app.services.dishes.get_client") as mock_dish_gc:
                mock_dish_gc.return_value = make_mock_client(data=None)
                client.patch("/order-items/payment-status", json={"itemIds": ["item-1"], "status": "paid"})

        assert mock_q.update.called

    def test_payment_status_returns_404_for_wrong_tenant(self, client: TestClient):
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = make_mock_client(
                data=[{"id": "item-1", "order": {"tenant_id": "other-tenant"}}]
            )
            resp = client.patch(
                "/order-items/payment-status",
                json={"itemIds": ["item-1"], "status": "assigned"},
            )

        assert resp.status_code == 404

    def test_payment_status_mixed_tenants_returns_404(self, client: TestClient):
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = make_mock_client(data=[
                {"id": "item-1", "order": {"tenant_id": VALID_TENANT_ID}},
                {"id": "item-2", "order": {"tenant_id": "other-tenant"}},
            ])
            resp = client.patch(
                "/order-items/payment-status",
                json={"itemIds": ["item-1", "item-2"], "status": "paid"},
            )

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /order-items/{item_id} — ownership check
# ---------------------------------------------------------------------------

class TestDeleteOrderItem:
    def test_returns_200_for_correct_tenant(self, client: TestClient):
        mock_q = make_mock_client()
        mock_q.execute.side_effect = [
            MagicMock(data=[{"order_id": "order-1", "order": {"tenant_id": VALID_TENANT_ID}}]),
            MagicMock(data=[]),   # item details for stock (empty → skip)
            MagicMock(data=[]),   # get_order_by_id → recalculate skips
            MagicMock(data=None), # delete
        ]
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = mock_q
            with patch("app.db.supabase.verify_token_full", return_value=(VALID_USER_ID, VALID_TENANT_ID, "staff")):
                resp = client.delete("/order-items/item-1", headers=_auth_headers())

        assert resp.status_code == 200

    def test_returns_404_for_wrong_tenant(self, client: TestClient):
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = make_mock_client(
                data=[{"order_id": "order-1", "order": {"tenant_id": "other-tenant"}}]
            )
            with patch("app.db.supabase.verify_token_full", return_value=(VALID_USER_ID, VALID_TENANT_ID, "staff")):
                resp = client.delete("/order-items/item-1", headers=_auth_headers())

        assert resp.status_code == 404

    def test_returns_404_when_item_not_found(self, client: TestClient):
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = make_mock_client(data=[])
            with patch("app.db.supabase.verify_token_full", return_value=(VALID_USER_ID, VALID_TENANT_ID, "staff")):
                resp = client.delete("/order-items/nonexistent", headers=_auth_headers())

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /order-items/{item_id}/quantity — ownership check
# ---------------------------------------------------------------------------

class TestUpdateOrderItemQuantity:
    def test_returns_200_for_correct_tenant(self, client: TestClient):
        mock_q = make_mock_client()
        mock_q.execute.side_effect = [
            MagicMock(data=[{"order_id": "order-1", "order": {"tenant_id": VALID_TENANT_ID}}]),
            MagicMock(data=[]),   # item details for stock
            MagicMock(data=[]),   # get_order_by_id
            MagicMock(data=None), # update
        ]
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = mock_q
            with patch("app.db.supabase.verify_token_full", return_value=(VALID_USER_ID, VALID_TENANT_ID, "staff")):
                resp = client.patch("/order-items/item-1/quantity", json={"quantity": 3}, headers=_auth_headers())

        assert resp.status_code == 200

    def test_returns_404_for_wrong_tenant(self, client: TestClient):
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = make_mock_client(
                data=[{"order_id": "order-1", "order": {"tenant_id": "other-tenant"}}]
            )
            with patch("app.db.supabase.verify_token_full", return_value=(VALID_USER_ID, VALID_TENANT_ID, "staff")):
                resp = client.patch("/order-items/item-1/quantity", json={"quantity": 3}, headers=_auth_headers())

        assert resp.status_code == 404

    def test_returns_404_when_item_not_found(self, client: TestClient):
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = make_mock_client(data=[])
            with patch("app.db.supabase.verify_token_full", return_value=(VALID_USER_ID, VALID_TENANT_ID, "staff")):
                resp = client.patch("/order-items/item-1/quantity", json={"quantity": 3}, headers=_auth_headers())

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /order-items/{item_id}/price — ownership check
# ---------------------------------------------------------------------------

class TestUpdateOrderItemPrice:
    def test_returns_200_for_correct_tenant(self, client: TestClient):
        mock_q = make_mock_client()
        mock_q.execute.side_effect = [
            MagicMock(data=[{"order_id": "order-1", "order": {"tenant_id": VALID_TENANT_ID}}]),
            MagicMock(data=[{"dish_price": 10.0, "original_price": None}]),
            MagicMock(data=[]),   # get_order_by_id
            MagicMock(data=None), # update
        ]
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = mock_q
            with patch("app.db.supabase.verify_token_full", return_value=(VALID_USER_ID, VALID_TENANT_ID, "staff")):
                resp = client.patch("/order-items/item-1/price", json={"price": 8.0}, headers=_auth_headers())

        assert resp.status_code == 200

    def test_returns_404_for_wrong_tenant(self, client: TestClient):
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = make_mock_client(
                data=[{"order_id": "order-1", "order": {"tenant_id": "other-tenant"}}]
            )
            with patch("app.db.supabase.verify_token_full", return_value=(VALID_USER_ID, VALID_TENANT_ID, "staff")):
                resp = client.patch("/order-items/item-1/price", json={"price": 8.0}, headers=_auth_headers())

        assert resp.status_code == 404

    def test_returns_404_when_item_not_found(self, client: TestClient):
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = make_mock_client(data=[])
            with patch("app.db.supabase.verify_token_full", return_value=(VALID_USER_ID, VALID_TENANT_ID, "staff")):
                resp = client.patch("/order-items/item-1/price", json={"price": 8.0}, headers=_auth_headers())

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /api/order-items/{item_id}/split-portions
# ---------------------------------------------------------------------------

class TestUpdateSplitPortions:
    def test_update_split_portions_returns_200(self, client: TestClient):
        mock_q = make_mock_client()
        mock_q.execute.side_effect = [
            MagicMock(data=_owner_row()),  # _assert_item_owner
            MagicMock(data=[{"paid_portions": 0, "payment_status": "unassigned"}]),  # select paid_portions
            MagicMock(data=None),  # update split_portions
        ]
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = mock_q
            resp = client.patch(
                "/order-items/item-1/split-portions",
                json={"splitPortions": 3},
            )
        assert resp.status_code == 200
        assert resp.json() == {"data": None, "error": None}

    def test_update_split_portions_rejects_paid_item(self, client: TestClient):
        mock_q = make_mock_client()
        mock_q.execute.side_effect = [
            MagicMock(data=_owner_row()),  # _assert_item_owner
            MagicMock(data=[{"paid_portions": 2, "payment_status": "paid"}]),  # select paid_portions
        ]
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = mock_q
            resp = client.patch(
                "/order-items/item-1/split-portions",
                json={"splitPortions": 3},
            )
        assert resp.status_code == 400
        assert "cannot split paid item" in resp.json()["error"]

    def test_update_split_portions_rejects_less_than_paid(self, client: TestClient):
        mock_q = make_mock_client()
        mock_q.execute.side_effect = [
            MagicMock(data=_owner_row()),  # _assert_item_owner
            MagicMock(data=[{"paid_portions": 2, "payment_status": "unassigned"}]),  # select paid_portions
        ]
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = mock_q
            resp = client.patch(
                "/order-items/item-1/split-portions",
                json={"splitPortions": 1},
            )
        assert resp.status_code == 400
        assert "cannot be less than paid_portions" in resp.json()["error"]


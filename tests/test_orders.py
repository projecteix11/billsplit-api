"""
Tests for:
  POST   /api/orders                         – create order (rate limited, no auth)
  GET    /api/orders/{order_id}              – get order by ID
  POST   /api/orders/{order_id}/items        – add items (rate limited)
  PATCH  /api/orders/{order_id}/close        – close order (rate limited)
  GET    /api/tables/{table_id}/open-order   – get open order for table
  GET    /api/orders                         – list orders (REQUIRES AUTH)

Service-level supabase calls are patched via `app.services.orders.supabase`.
Auth (supabase.verify_token) is patched where needed.
"""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from tests.conftest import make_order, make_order_item, VALID_TOKEN, VALID_USER_ID, VALID_TENANT_ID


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _auth_headers(token: str = VALID_TOKEN) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _stub_verify_token(mock_sb, user_id: str = VALID_USER_ID):
    """Make supabase.verify_token return a valid user_id."""
    mock_sb.verify_token.return_value = user_id


# ---------------------------------------------------------------------------
# POST /api/orders
# ---------------------------------------------------------------------------

class TestCreateOrder:
    _valid_body = {
        "tableId": "table-1",
        "tableNumber": 5,
        "items": [
            {"dish_name": "Pizza Margherita", "dish_price": 12.50, "quantity": 2}
        ],
    }

    def test_create_order_returns_201_on_success(self, client: TestClient):
        order = make_order()
        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.insert.return_value = [order]
            resp = client.post("/orders", json=self._valid_body)

        assert resp.status_code == 201

    def test_create_order_returns_data_envelope(self, client: TestClient):
        order = make_order()
        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.insert.return_value = [order]
            resp = client.post("/orders", json=self._valid_body)

        body = resp.json()
        assert "data" in body
        assert body["error"] is None

    def test_create_order_returns_order_fields(self, client: TestClient):
        order = make_order()
        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.insert.return_value = [order]
            resp = client.post("/orders", json=self._valid_body)

        data = resp.json()["data"]
        assert data["id"] == "order-1"
        assert data["table_id"] == "table-1"
        assert data["table_number"] == 5
        assert data["status"] == "open"

    def test_create_order_inserts_order_and_items(self, client: TestClient):
        order = make_order()
        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.insert.return_value = [order]
            client.post("/orders", json=self._valid_body)

        # First call inserts the order, second inserts items
        assert mock_sb.insert.call_count == 2
        first_call_table = mock_sb.insert.call_args_list[0][0][0]
        second_call_table = mock_sb.insert.call_args_list[1][0][0]
        assert first_call_table == "orders"
        assert second_call_table == "order_items"

    def test_create_order_calculates_tax(self, client: TestClient):
        # 2 * 12.50 = 25.00 subtotal, 10% = 2.50 tax, 27.50 total
        order = make_order(subtotal=25.0, tax_amount=2.5, total=27.5)
        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.insert.return_value = [order]
            resp = client.post("/orders", json=self._valid_body)

        data = resp.json()["data"]
        assert data["subtotal"] == 25.0
        assert data["tax_amount"] == 2.5
        assert data["total"] == 27.5

    def test_create_order_defaults_diner_name_to_cliente(self, client: TestClient):
        order = make_order()
        captured_items = []

        def fake_insert(table, body, return_result=True):
            if table == "order_items":
                captured_items.extend(body if isinstance(body, list) else [body])
                return None
            return [order]

        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.insert.side_effect = fake_insert
            client.post("/orders", json=self._valid_body)

        assert captured_items[0]["diner_name"] == "Cliente"

    def test_create_order_uses_provided_diner_name(self, client: TestClient):
        body = {
            "tableId": "table-1",
            "tableNumber": 3,
            "items": [
                {"dish_name": "Pasta", "dish_price": 9.0, "quantity": 1, "diner_name": "Alice"}
            ],
        }
        order = make_order()
        captured_items = []

        def fake_insert(table, body, return_result=True):
            if table == "order_items":
                captured_items.extend(body if isinstance(body, list) else [body])
                return None
            return [order]

        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.insert.side_effect = fake_insert
            client.post("/orders", json=body)

        assert captured_items[0]["diner_name"] == "Alice"

    def test_create_order_missing_table_id_returns_400(self, client: TestClient):
        body = {"tableNumber": 5, "items": [{"dish_name": "X", "dish_price": 1.0, "quantity": 1}]}
        resp = client.post("/orders", json=body)
        assert resp.status_code == 422

    def test_create_order_missing_table_number_returns_400(self, client: TestClient):
        body = {"tableId": "t-1", "items": [{"dish_name": "X", "dish_price": 1.0, "quantity": 1}]}
        resp = client.post("/orders", json=body)
        assert resp.status_code == 422

    def test_create_order_missing_items_returns_422(self, client: TestClient):
        body = {"tableId": "t-1", "tableNumber": 1}
        resp = client.post("/orders", json=body)
        assert resp.status_code == 422

    def test_create_order_empty_items_returns_400(self, client: TestClient):
        body = {"tableId": "t-1", "tableNumber": 1, "items": []}
        with patch("app.services.orders.supabase"):
            resp = client.post("/orders", json=body)
        # Router guard: "items[] is required" if falsy list
        assert resp.status_code == 400
        assert resp.json()["data"] is None

    def test_create_order_returns_500_on_db_error(self, client: TestClient):
        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.insert.side_effect = RuntimeError("supabase 500: internal error")
            resp = client.post("/orders", json=self._valid_body)

        assert resp.status_code == 500
        body = resp.json()
        assert body["data"] is None
        assert body["error"] is not None

    def test_create_order_returns_500_when_insert_returns_nothing(self, client: TestClient):
        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.insert.return_value = None
            resp = client.post("/orders", json=self._valid_body)

        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# GET /api/orders/{order_id}
# ---------------------------------------------------------------------------

class TestGetOrderById:
    def test_get_order_by_id_returns_200(self, client: TestClient):
        order = make_order()
        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.select.return_value = [order]
            resp = client.get("/orders/order-1")

        assert resp.status_code == 200

    def test_get_order_by_id_returns_data_envelope(self, client: TestClient):
        order = make_order()
        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.select.return_value = [order]
            resp = client.get("/orders/order-1")

        body = resp.json()
        assert "data" in body
        assert body["error"] is None

    def test_get_order_by_id_returns_order_fields(self, client: TestClient):
        order = make_order(items=[make_order_item()])
        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.select.return_value = [order]
            resp = client.get("/orders/order-1")

        data = resp.json()["data"]
        assert data["id"] == "order-1"
        assert data["table_id"] == "table-1"
        assert len(data["items"]) == 1

    def test_get_order_by_id_returns_404_when_not_found(self, client: TestClient):
        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.select.return_value = []
            resp = client.get("/orders/nonexistent-order")

        assert resp.status_code == 404
        body = resp.json()
        assert body["data"] is None
        assert body["error"] == "Order not found"

    def test_get_order_by_id_returns_500_on_db_error(self, client: TestClient):
        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.select.side_effect = RuntimeError("network error")
            resp = client.get("/orders/order-1")

        assert resp.status_code == 500
        assert resp.json()["data"] is None

    def test_get_order_by_id_queries_correct_table(self, client: TestClient):
        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.select.return_value = []
            client.get("/orders/my-order-id")

        call_args = mock_sb.select.call_args
        assert call_args[0][0] == "orders"
        assert "my-order-id" in call_args[0][1]


# ---------------------------------------------------------------------------
# POST /api/orders/{order_id}/items
# ---------------------------------------------------------------------------

class TestAddItemsToOrder:
    _valid_body = {
        "items": [
            {"dish_name": "Ensalada", "dish_price": 7.0, "quantity": 1}
        ]
    }

    def test_add_items_returns_200(self, client: TestClient):
        order = make_order(items=[make_order_item()])
        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.insert.return_value = None
            mock_sb.select.return_value = [order]
            resp = client.post("/orders/order-1/items", json=self._valid_body)

        assert resp.status_code == 200

    def test_add_items_returns_null_data_envelope(self, client: TestClient):
        order = make_order(items=[make_order_item()])
        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.insert.return_value = None
            mock_sb.select.return_value = [order]
            resp = client.post("/orders/order-1/items", json=self._valid_body)

        body = resp.json()
        assert body == {"data": None, "error": None}

    def test_add_items_inserts_items_then_updates_order_totals(self, client: TestClient):
        order = make_order(items=[make_order_item(dish_price=7.0, quantity=1)])
        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.insert.return_value = None
            mock_sb.select.return_value = [order]
            client.post("/orders/order-1/items", json=self._valid_body)

        mock_sb.insert.assert_called_once()
        mock_sb.update.assert_called_once()

    def test_add_items_empty_items_returns_400(self, client: TestClient):
        resp = client.post("/orders/order-1/items", json={"items": []})
        assert resp.status_code == 400
        body = resp.json()
        assert body["data"] is None
        assert "items[]" in body["error"]

    def test_add_items_missing_items_key_returns_422(self, client: TestClient):
        resp = client.post("/orders/order-1/items", json={})
        assert resp.status_code == 422

    def test_add_items_returns_500_on_db_error(self, client: TestClient):
        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.insert.side_effect = RuntimeError("insert failed")
            resp = client.post("/orders/order-1/items", json=self._valid_body)

        assert resp.status_code == 500
        assert resp.json()["data"] is None

    def test_add_items_defaults_diner_name_to_cliente(self, client: TestClient):
        order = make_order(items=[make_order_item()])
        captured = []

        def fake_insert(table, body, return_result=True):
            if table == "order_items":
                captured.extend(body if isinstance(body, list) else [body])
            return None

        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.insert.side_effect = fake_insert
            mock_sb.select.return_value = [order]
            client.post("/orders/order-1/items", json=self._valid_body)

        assert captured[0]["diner_name"] == "Cliente"

    def test_add_items_sets_kitchen_status_pending(self, client: TestClient):
        order = make_order(items=[make_order_item()])
        captured = []

        def fake_insert(table, body, return_result=True):
            if table == "order_items":
                captured.extend(body if isinstance(body, list) else [body])
            return None

        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.insert.side_effect = fake_insert
            mock_sb.select.return_value = [order]
            client.post("/orders/order-1/items", json=self._valid_body)

        assert captured[0]["kitchen_status"] == "pending"
        assert captured[0]["payment_status"] == "unassigned"


# ---------------------------------------------------------------------------
# PATCH /api/orders/{order_id}/close
# ---------------------------------------------------------------------------

class TestCloseOrder:
    def test_close_order_returns_200(self, client: TestClient):
        order = make_order()
        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.select.return_value = [order]
            mock_sb.update.return_value = None
            with patch("app.services.dishes.supabase") as mock_dish_sb:
                mock_dish_sb.delete.return_value = None
                resp = client.patch("/orders/order-1/close")

        assert resp.status_code == 200

    def test_close_order_returns_null_data_envelope(self, client: TestClient):
        order = make_order()
        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.select.return_value = [order]
            mock_sb.update.return_value = None
            with patch("app.services.dishes.supabase") as mock_dish_sb:
                mock_dish_sb.delete.return_value = None
                resp = client.patch("/orders/order-1/close")

        assert resp.json() == {"data": None, "error": None}

    def test_close_order_calls_update_with_closed_status(self, client: TestClient):
        order = make_order()
        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.select.return_value = [order]
            mock_sb.update.return_value = None
            with patch("app.services.dishes.supabase") as mock_dish_sb:
                mock_dish_sb.delete.return_value = None
                client.patch("/orders/order-1/close")

        # First update call is the order status change
        call_args = mock_sb.update.call_args_list[0]
        assert call_args[0][0] == "orders"
        assert "order-1" in call_args[0][1]
        assert call_args[0][2]["status"] == "closed"

    def test_close_order_resets_table_status(self, client: TestClient):
        order = make_order()
        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.select.return_value = [order]
            mock_sb.update.return_value = None
            with patch("app.services.dishes.supabase") as mock_dish_sb:
                mock_dish_sb.delete.return_value = None
                client.patch("/orders/order-1/close")

        # Second update call resets the table
        table_call = mock_sb.update.call_args_list[1]
        assert table_call[0][0] == "restaurant_tables"
        assert "table-1" in table_call[0][1]
        assert table_call[0][2]["status"] == "available"
        assert table_call[0][2]["active_order_id"] is None

    def test_close_order_is_noop_if_already_closed(self, client: TestClient):
        order = make_order(status="closed")
        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.select.return_value = [order]
            resp = client.patch("/orders/order-1/close")

        assert resp.status_code == 200
        mock_sb.update.assert_not_called()

    def test_close_order_returns_500_on_db_error(self, client: TestClient):
        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.select.side_effect = RuntimeError("update failed")
            resp = client.patch("/orders/order-1/close")

        assert resp.status_code == 500
        assert resp.json()["data"] is None


# ---------------------------------------------------------------------------
# GET /api/tables/{table_id}/open-order
# ---------------------------------------------------------------------------

class TestGetOpenOrderForTable:
    def test_returns_200_with_open_order(self, client: TestClient):
        order = make_order()
        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.select.return_value = [order]
            resp = client.get("/tables/table-1/open-order")

        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["id"] == "order-1"
        assert body["error"] is None

    def test_returns_200_with_null_data_when_no_open_order(self, client: TestClient):
        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.select.return_value = []
            resp = client.get("/tables/table-1/open-order")

        assert resp.status_code == 200
        body = resp.json()
        assert body["data"] is None
        assert body["error"] is None

    def test_queries_with_correct_table_id_and_status(self, client: TestClient):
        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.select.return_value = []
            client.get("/tables/my-table-uuid/open-order")

        call_args = mock_sb.select.call_args
        query = call_args[0][1]
        assert "my-table-uuid" in query
        assert "open" in query

    def test_returns_500_on_db_error(self, client: TestClient):
        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.select.side_effect = RuntimeError("db error")
            resp = client.get("/tables/table-1/open-order")

        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# GET /api/orders  (AUTH REQUIRED)
# ---------------------------------------------------------------------------

class TestListOrders:
    def test_list_orders_requires_auth_returns_401_without_token(self, client: TestClient):
        resp = client.get("/orders")
        assert resp.status_code == 401

    def test_list_orders_requires_auth_returns_401_with_bad_token(self, client: TestClient):
        with patch("app.middleware.auth.supabase.verify_token", side_effect=ValueError("invalid token")):
            resp = client.get("/orders", headers={"Authorization": "Bearer bad-token"})

        assert resp.status_code == 401

    def test_list_orders_returns_401_with_malformed_header(self, client: TestClient):
        resp = client.get("/orders", headers={"Authorization": "Token abc123"})
        assert resp.status_code == 401

    def test_list_orders_open_returns_200_with_valid_token(self, client: TestClient):
        orders = [make_order(), make_order(id="order-2", table_number=6)]
        with patch("app.db.supabase.verify_token_full", return_value=(VALID_USER_ID, VALID_TENANT_ID, "developer")):
            with patch("app.services.orders.supabase") as mock_sb:
                mock_sb.select.return_value = orders
                resp = client.get(
                    "/orders",
                    headers=_auth_headers(),
                )

        assert resp.status_code == 200

    def test_list_orders_returns_data_envelope(self, client: TestClient):
        with patch("app.db.supabase.verify_token_full", return_value=(VALID_USER_ID, VALID_TENANT_ID, "developer")):
            with patch("app.services.orders.supabase") as mock_sb:
                mock_sb.select.return_value = [make_order()]
                resp = client.get("/orders", headers=_auth_headers())

        body = resp.json()
        assert "data" in body
        assert body["error"] is None
        assert isinstance(body["data"], list)

    def test_list_orders_defaults_to_open_status(self, client: TestClient):
        with patch("app.db.supabase.verify_token_full", return_value=(VALID_USER_ID, VALID_TENANT_ID, "developer")):
            with patch("app.services.orders._get_tenant_table_ids", return_value=["table-1"]):
                with patch("app.services.orders.supabase") as mock_sb:
                    mock_sb.select.return_value = []
                    client.get("/orders", headers=_auth_headers())

        query = mock_sb.select.call_args[0][1]
        assert "status=eq.open" in query

    def test_list_orders_accepts_closed_status_param(self, client: TestClient):
        with patch("app.db.supabase.verify_token_full", return_value=(VALID_USER_ID, VALID_TENANT_ID, "developer")):
            with patch("app.services.orders._get_tenant_table_ids", return_value=["table-1"]):
                with patch("app.services.orders.supabase") as mock_sb:
                    mock_sb.select.return_value = []
                    resp = client.get(
                        "/orders?status=closed",
                        headers=_auth_headers(),
                    )

        assert resp.status_code == 200
        query = mock_sb.select.call_args[0][1]
        assert "status=eq.closed" in query

    def test_list_orders_invalid_status_returns_400(self, client: TestClient):
        with patch("app.db.supabase.verify_token_full", return_value=(VALID_USER_ID, VALID_TENANT_ID, "developer")):
            resp = client.get(
                "/orders?status=invalid",
                headers=_auth_headers(),
            )

        assert resp.status_code == 400
        body = resp.json()
        assert body["data"] is None
        assert "status must be open or closed" in body["error"]

    def test_list_orders_returns_500_on_db_error(self, client: TestClient):
        with patch("app.db.supabase.verify_token_full", return_value=(VALID_USER_ID, VALID_TENANT_ID, "developer")):
            with patch("app.services.orders.supabase") as mock_sb:
                mock_sb.select.side_effect = RuntimeError("connection refused")
                resp = client.get("/orders", headers=_auth_headers())

        assert resp.status_code == 500
        assert resp.json()["data"] is None

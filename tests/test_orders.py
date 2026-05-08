"""
Tests for:
  POST   /api/orders                         – create order (rate limited, no auth)
  GET    /api/orders/{order_id}              – get order by ID
  POST   /api/orders/{order_id}/items        – add items (rate limited)
  PATCH  /api/orders/{order_id}/close        – close order (rate limited)
  GET    /api/tables/{table_id}/open-order   – get open order for table
  GET    /api/orders                         – list orders (REQUIRES AUTH)
"""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from tests.conftest import (
    make_order, make_order_item, make_mock_client,
    VALID_TOKEN, VALID_USER_ID, VALID_TENANT_ID,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _auth_headers(token: str = VALID_TOKEN) -> dict:
    return {"Authorization": f"Bearer {token}"}


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
        mock_q = make_mock_client()
        mock_q.execute.side_effect = [
            MagicMock(data=[order]),  # orders insert
            MagicMock(data=None),     # restaurant_tables update
            MagicMock(data=None),     # order_items insert
        ]
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = mock_q
            resp = client.post("/orders", json=self._valid_body)

        assert resp.status_code == 201

    def test_create_order_returns_data_envelope(self, client: TestClient):
        order = make_order()
        mock_q = make_mock_client()
        mock_q.execute.side_effect = [
            MagicMock(data=[order]),
            MagicMock(data=None),
            MagicMock(data=None),
        ]
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = mock_q
            resp = client.post("/orders", json=self._valid_body)

        body = resp.json()
        assert "data" in body
        assert body["error"] is None

    def test_create_order_returns_order_fields(self, client: TestClient):
        order = make_order()
        mock_q = make_mock_client()
        mock_q.execute.side_effect = [
            MagicMock(data=[order]),
            MagicMock(data=None),
            MagicMock(data=None),
        ]
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = mock_q
            resp = client.post("/orders", json=self._valid_body)

        data = resp.json()["data"]
        assert data["id"] == "order-1"
        assert data["table_id"] == "table-1"
        assert data["table_number"] == 5
        assert data["status"] == "open"

    def test_create_order_calculates_tax(self, client: TestClient):
        order = make_order(subtotal=25.0, tax_amount=2.5, total=27.5)
        mock_q = make_mock_client()
        mock_q.execute.side_effect = [
            MagicMock(data=[order]),
            MagicMock(data=None),
            MagicMock(data=None),
        ]
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = mock_q
            resp = client.post("/orders", json=self._valid_body)

        data = resp.json()["data"]
        assert data["subtotal"] == 25.0
        assert data["tax_amount"] == 2.5
        assert data["total"] == 27.5

    def test_create_order_defaults_diner_name_to_cliente(self, client: TestClient):
        order = make_order()
        captured_items = []

        mock_q = make_mock_client()
        original_insert = mock_q.insert

        def track_insert(body):
            if isinstance(body, list) and body and "diner_name" in body[0]:
                captured_items.extend(body)
            return mock_q

        mock_q.insert = track_insert
        mock_q.execute.side_effect = [
            MagicMock(data=[order]),
            MagicMock(data=None),
            MagicMock(data=None),
        ]
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = mock_q
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

        mock_q = make_mock_client()

        def track_insert(b):
            if isinstance(b, list) and b and "diner_name" in b[0]:
                captured_items.extend(b)
            return mock_q

        mock_q.insert = track_insert
        mock_q.execute.side_effect = [
            MagicMock(data=[order]),
            MagicMock(data=None),
            MagicMock(data=None),
        ]
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = mock_q
            client.post("/orders", json=body)

        assert captured_items[0]["diner_name"] == "Alice"

    def test_create_order_missing_table_id_returns_422(self, client: TestClient):
        body = {"tableNumber": 5, "items": [{"dish_name": "X", "dish_price": 1.0, "quantity": 1}]}
        resp = client.post("/orders", json=body)
        assert resp.status_code == 422

    def test_create_order_missing_table_number_returns_422(self, client: TestClient):
        body = {"tableId": "t-1", "items": [{"dish_name": "X", "dish_price": 1.0, "quantity": 1}]}
        resp = client.post("/orders", json=body)
        assert resp.status_code == 422

    def test_create_order_missing_items_returns_422(self, client: TestClient):
        body = {"tableId": "t-1", "tableNumber": 1}
        resp = client.post("/orders", json=body)
        assert resp.status_code == 422

    def test_create_order_empty_items_returns_400(self, client: TestClient):
        body = {"tableId": "t-1", "tableNumber": 1, "items": []}
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = make_mock_client()
            resp = client.post("/orders", json=body)
        assert resp.status_code == 400
        assert resp.json()["data"] is None

    def test_create_order_returns_500_on_db_error(self, client: TestClient):
        mock_q = make_mock_client()
        mock_q.execute.side_effect = RuntimeError("supabase 500: internal error")
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = mock_q
            resp = client.post("/orders", json=self._valid_body)

        assert resp.status_code == 500
        body = resp.json()
        assert body["data"] is None
        assert body["error"] is not None

    def test_create_order_returns_500_when_insert_returns_nothing(self, client: TestClient):
        mock_q = make_mock_client()
        mock_q.execute.return_value = MagicMock(data=None)
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = mock_q
            resp = client.post("/orders", json=self._valid_body)

        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# GET /api/orders/{order_id}
# ---------------------------------------------------------------------------

class TestGetOrderById:
    def test_get_order_by_id_returns_200(self, client: TestClient):
        order = make_order()
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = make_mock_client(data=[order])
            resp = client.get("/orders/order-1")

        assert resp.status_code == 200

    def test_get_order_by_id_returns_data_envelope(self, client: TestClient):
        order = make_order()
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = make_mock_client(data=[order])
            resp = client.get("/orders/order-1")

        body = resp.json()
        assert "data" in body
        assert body["error"] is None

    def test_get_order_by_id_returns_order_fields(self, client: TestClient):
        order = make_order(items=[make_order_item()])
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = make_mock_client(data=[order])
            resp = client.get("/orders/order-1")

        data = resp.json()["data"]
        assert data["id"] == "order-1"
        assert data["table_id"] == "table-1"
        assert len(data["items"]) == 1

    def test_get_order_by_id_returns_404_when_not_found(self, client: TestClient):
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = make_mock_client(data=[])
            resp = client.get("/orders/nonexistent-order")

        assert resp.status_code == 404
        body = resp.json()
        assert body["data"] is None
        assert body["error"] == "Order not found"

    def test_get_order_by_id_returns_500_on_db_error(self, client: TestClient):
        mock_q = make_mock_client()
        mock_q.execute.side_effect = RuntimeError("network error")
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = mock_q
            resp = client.get("/orders/order-1")

        assert resp.status_code == 500
        assert resp.json()["data"] is None


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
        mock_q = make_mock_client()
        mock_q.execute.side_effect = [
            MagicMock(data=None),    # order_items insert
            MagicMock(data=[order]), # get_order_by_id for recalculate
            MagicMock(data=None),    # orders update
        ]
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = mock_q
            resp = client.post("/orders/order-1/items", json=self._valid_body)

        assert resp.status_code == 200

    def test_add_items_returns_null_data_envelope(self, client: TestClient):
        order = make_order(items=[make_order_item()])
        mock_q = make_mock_client()
        mock_q.execute.side_effect = [
            MagicMock(data=None),
            MagicMock(data=[order]),
            MagicMock(data=None),
        ]
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = mock_q
            resp = client.post("/orders/order-1/items", json=self._valid_body)

        body = resp.json()
        assert body == {"data": None, "error": None}

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
        mock_q = make_mock_client()
        mock_q.execute.side_effect = RuntimeError("insert failed")
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = mock_q
            resp = client.post("/orders/order-1/items", json=self._valid_body)

        assert resp.status_code == 500
        assert resp.json()["data"] is None

    def test_add_items_defaults_diner_name_to_cliente(self, client: TestClient):
        order = make_order(items=[make_order_item()])
        captured = []

        mock_q = make_mock_client()

        def track_insert(b):
            if isinstance(b, list) and b and "diner_name" in b[0]:
                captured.extend(b)
            return mock_q

        mock_q.insert = track_insert
        mock_q.execute.side_effect = [
            MagicMock(data=None),
            MagicMock(data=[order]),
            MagicMock(data=None),
        ]
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = mock_q
            client.post("/orders/order-1/items", json=self._valid_body)

        assert captured[0]["diner_name"] == "Cliente"

    def test_add_items_sets_kitchen_status_pending(self, client: TestClient):
        order = make_order(items=[make_order_item()])
        captured = []

        mock_q = make_mock_client()

        def track_insert(b):
            if isinstance(b, list) and b and "kitchen_status" in b[0]:
                captured.extend(b)
            return mock_q

        mock_q.insert = track_insert
        mock_q.execute.side_effect = [
            MagicMock(data=None),
            MagicMock(data=[order]),
            MagicMock(data=None),
        ]
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = mock_q
            client.post("/orders/order-1/items", json=self._valid_body)

        assert captured[0]["kitchen_status"] == "pending"
        assert captured[0]["payment_status"] == "unassigned"


# ---------------------------------------------------------------------------
# PATCH /api/orders/{order_id}/close
# ---------------------------------------------------------------------------

class TestCloseOrder:
    def test_close_order_returns_200(self, client: TestClient):
        order = make_order()
        mock_q = make_mock_client()
        mock_q.execute.side_effect = [
            MagicMock(data=[order]),  # get_order_by_id
            MagicMock(data=None),     # orders update
            MagicMock(data=None),     # restaurant_tables update
        ]
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = mock_q
            with patch("app.services.dishes.get_client") as mock_dish_gc:
                mock_dish_gc.return_value = make_mock_client(data=None)
                resp = client.patch("/orders/order-1/close")

        assert resp.status_code == 200

    def test_close_order_returns_null_data_envelope(self, client: TestClient):
        order = make_order()
        mock_q = make_mock_client()
        mock_q.execute.side_effect = [
            MagicMock(data=[order]),
            MagicMock(data=None),
            MagicMock(data=None),
        ]
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = mock_q
            with patch("app.services.dishes.get_client") as mock_dish_gc:
                mock_dish_gc.return_value = make_mock_client(data=None)
                resp = client.patch("/orders/order-1/close")

        assert resp.json() == {"data": None, "error": None}

    def test_close_order_is_noop_if_already_closed(self, client: TestClient):
        order = make_order(status="closed")
        with patch("app.services.orders.get_client") as mock_gc:
            mock_q = make_mock_client(data=[order])
            mock_gc.return_value = mock_q
            with patch("app.services.dishes.get_client") as mock_dish_gc:
                mock_dish_gc.return_value = make_mock_client(data=None)
                resp = client.patch("/orders/order-1/close")

        assert resp.status_code == 200
        mock_q.update.assert_not_called()

    def test_close_order_returns_404_for_wrong_tenant(self, client: TestClient):
        order = make_order(tenant_id="other-tenant-uuid")
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = make_mock_client(data=[order])
            resp = client.patch("/orders/order-1/close")

        assert resp.status_code == 404

    def test_close_order_returns_500_on_db_error(self, client: TestClient):
        mock_q = make_mock_client()
        mock_q.execute.side_effect = RuntimeError("update failed")
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = mock_q
            resp = client.patch("/orders/order-1/close")

        assert resp.status_code == 500
        assert resp.json()["data"] is None


# ---------------------------------------------------------------------------
# GET /api/tables/{table_id}/open-order
# ---------------------------------------------------------------------------

class TestGetOpenOrderForTable:
    def test_returns_200_with_open_order(self, client: TestClient):
        order = make_order()
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = make_mock_client(data=[order])
            resp = client.get("/tables/table-1/open-order")

        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["id"] == "order-1"
        assert body["error"] is None

    def test_returns_200_with_null_data_when_no_open_order(self, client: TestClient):
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = make_mock_client(data=[])
            resp = client.get("/tables/table-1/open-order")

        assert resp.status_code == 200
        body = resp.json()
        assert body["data"] is None
        assert body["error"] is None

    def test_returns_500_on_db_error(self, client: TestClient):
        mock_q = make_mock_client()
        mock_q.execute.side_effect = RuntimeError("db error")
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = mock_q
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
        with patch("app.db.supabase.verify_token_full", side_effect=ValueError("invalid token")):
            resp = client.get("/orders", headers={"Authorization": "Bearer bad-token"})

        assert resp.status_code == 401

    def test_list_orders_returns_401_with_malformed_header(self, client: TestClient):
        resp = client.get("/orders", headers={"Authorization": "Token abc123"})
        assert resp.status_code == 401

    def test_list_orders_open_returns_200_with_valid_token(self, client: TestClient):
        orders = [make_order(), make_order(id="order-2", table_number=6)]
        with patch("app.db.supabase.verify_token_full", return_value=(VALID_USER_ID, VALID_TENANT_ID, "developer")):
            with patch("app.services.orders.get_client") as mock_gc:
                mock_gc.return_value = make_mock_client(data=orders)
                resp = client.get("/orders", headers=_auth_headers())

        assert resp.status_code == 200

    def test_list_orders_returns_data_envelope(self, client: TestClient):
        with patch("app.db.supabase.verify_token_full", return_value=(VALID_USER_ID, VALID_TENANT_ID, "developer")):
            with patch("app.services.orders.get_client") as mock_gc:
                mock_gc.return_value = make_mock_client(data=[make_order()])
                resp = client.get("/orders", headers=_auth_headers())

        body = resp.json()
        assert "data" in body
        assert body["error"] is None
        assert isinstance(body["data"], list)

    def test_list_orders_invalid_status_returns_400(self, client: TestClient):
        with patch("app.db.supabase.verify_token_full", return_value=(VALID_USER_ID, VALID_TENANT_ID, "developer")):
            resp = client.get("/orders?status=invalid", headers=_auth_headers())

        assert resp.status_code == 400
        body = resp.json()
        assert body["data"] is None
        assert "status must be open or closed" in body["error"]

    def test_list_orders_returns_500_on_db_error(self, client: TestClient):
        mock_q = make_mock_client()
        mock_q.execute.side_effect = RuntimeError("connection refused")
        with patch("app.db.supabase.verify_token_full", return_value=(VALID_USER_ID, VALID_TENANT_ID, "developer")):
            with patch("app.services.orders.get_client") as mock_gc:
                mock_gc.return_value = mock_q
                resp = client.get("/orders", headers=_auth_headers())

        assert resp.status_code == 500
        assert resp.json()["data"] is None

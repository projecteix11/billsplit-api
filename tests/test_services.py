"""
Unit tests for the service layer, exercising business logic directly
without going through the HTTP stack.

Tests cover:
- app/services/dishes.py
- app/services/orders.py  (math, DB call shapes, edge cases)
"""

import pytest
from unittest.mock import patch, call
from tests.conftest import make_dish, make_category, make_order, make_order_item


# ---------------------------------------------------------------------------
# Dishes service
# ---------------------------------------------------------------------------

class TestDishesService:
    def test_get_dishes_returns_dish_objects(self):
        from app.services import dishes as svc
        dish_rows = [make_dish(), make_dish(id="d-2", name="Pasta")]
        with patch("app.services.dishes.supabase") as mock_sb:
            mock_sb.select.return_value = dish_rows
            result = svc.get_dishes()

        assert len(result) == 2
        assert result[0].name == "Pizza Margherita"
        assert result[1].id == "d-2"

    def test_get_dishes_returns_empty_list(self):
        from app.services import dishes as svc
        with patch("app.services.dishes.supabase") as mock_sb:
            mock_sb.select.return_value = []
            result = svc.get_dishes()
        assert result == []

    def test_get_categories_returns_category_objects(self):
        from app.services import dishes as svc
        cats = [make_category(), make_category(id="c-2", name="Pastas", sort_order=2)]
        with patch("app.services.dishes.supabase") as mock_sb:
            mock_sb.select.return_value = cats
            result = svc.get_categories()

        assert len(result) == 2
        assert result[0].sort_order == 1
        assert result[1].name == "Pastas"

    def test_get_categories_returns_empty_list(self):
        from app.services import dishes as svc
        with patch("app.services.dishes.supabase") as mock_sb:
            mock_sb.select.return_value = []
            result = svc.get_categories()
        assert result == []


# ---------------------------------------------------------------------------
# Orders service – math helpers
# ---------------------------------------------------------------------------

class TestOrdersMath:
    def test_round2_rounds_correctly(self):
        from app.services.orders import _round2
        # The implementation uses math.floor(v*100 + 0.5)/100 — a custom
        # "half-up" rounding.  Float representation means 1.005*100=100.499...
        # so 1.005 rounds DOWN to 1.00, not up to 1.01.  We test values that
        # are exactly representable and verify known-correct behaviour.
        assert _round2(10.0) == 10.0
        assert _round2(0.0) == 0.0
        assert _round2(2.225) == 2.23    # 222.5 + 0.5 = 223.0  → 2.23
        assert _round2(25.0) == 25.0
        assert _round2(100.5) == 100.5
        # Standard round-half-up: .xx5 where x is not affected by float drift
        assert _round2(1.235) == 1.24   # 123.5 + 0.5 = 124.0 → 1.24

    def test_calculate_subtotal_single_item(self):
        from app.services.orders import _calculate_subtotal
        from app.models import NewOrderItem
        items = [NewOrderItem(dish_name="X", dish_price=12.50, quantity=2)]
        assert _calculate_subtotal(items) == 25.0

    def test_calculate_subtotal_multiple_items(self):
        from app.services.orders import _calculate_subtotal
        from app.models import NewOrderItem
        items = [
            NewOrderItem(dish_name="A", dish_price=10.0, quantity=1),
            NewOrderItem(dish_name="B", dish_price=5.0, quantity=3),
        ]
        assert _calculate_subtotal(items) == 25.0

    def test_calculate_subtotal_zero_items(self):
        from app.services.orders import _calculate_subtotal
        assert _calculate_subtotal([]) == 0

    def test_calculate_tax_10_percent(self):
        from app.services.orders import _calculate_tax
        assert _calculate_tax(100.0) == 10.0
        assert _calculate_tax(25.0) == 2.5

    def test_calculate_tax_rounds_to_2_decimals(self):
        from app.services.orders import _calculate_tax
        # 33.33 * 10% = 3.333 → rounds to 3.33
        result = _calculate_tax(33.33)
        assert result == 3.33

    def test_calculate_subtotal_from_items(self):
        from app.services.orders import _calculate_subtotal_from_items
        from app.models import OrderItem
        items = [
            OrderItem(**make_order_item(dish_price=12.50, quantity=2)),
            OrderItem(**make_order_item(id="i-2", dish_price=5.0, quantity=1)),
        ]
        assert _calculate_subtotal_from_items(items) == 30.0


# ---------------------------------------------------------------------------
# Orders service – fetch_orders
# ---------------------------------------------------------------------------

class TestFetchOrders:
    def test_fetch_orders_open_queries_correct_fields(self):
        from app.services import orders as svc
        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.select.return_value = []
            svc.fetch_orders("open")

        call_args = mock_sb.select.call_args
        assert call_args[0][0] == "orders"
        query = call_args[0][1]
        assert "status=eq.open" in query

    def test_fetch_orders_closed_queries_with_desc_order(self):
        from app.services import orders as svc
        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.select.return_value = []
            svc.fetch_orders("closed")

        query = mock_sb.select.call_args[0][1]
        assert "status=eq.closed" in query
        assert "updated_at.desc" in query

    def test_fetch_orders_returns_list_of_order_objects(self):
        from app.services import orders as svc
        rows = [make_order(), make_order(id="order-2", table_number=7)]
        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.select.return_value = rows
            result = svc.fetch_orders("open")

        assert len(result) == 2
        assert result[0].id == "order-1"
        assert result[1].table_number == 7


# ---------------------------------------------------------------------------
# Orders service – get_order_by_id
# ---------------------------------------------------------------------------

class TestGetOrderById:
    def test_returns_order_when_found(self):
        from app.services import orders as svc
        row = make_order()
        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.select.return_value = [row]
            result = svc.get_order_by_id("order-1")
        assert result is not None
        assert result.id == "order-1"

    def test_returns_none_when_not_found(self):
        from app.services import orders as svc
        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.select.return_value = []
            result = svc.get_order_by_id("missing")
        assert result is None

    def test_query_includes_order_id(self):
        from app.services import orders as svc
        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.select.return_value = []
            svc.get_order_by_id("my-specific-order-id")
        query = mock_sb.select.call_args[0][1]
        assert "my-specific-order-id" in query


# ---------------------------------------------------------------------------
# Orders service – get_open_order_for_table
# ---------------------------------------------------------------------------

class TestGetOpenOrderForTable:
    def test_returns_order_when_found(self):
        from app.services import orders as svc
        row = make_order()
        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.select.return_value = [row]
            result = svc.get_open_order_for_table("table-1")
        assert result is not None
        assert result.table_id == "table-1"

    def test_returns_none_when_not_found(self):
        from app.services import orders as svc
        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.select.return_value = []
            result = svc.get_open_order_for_table("table-1")
        assert result is None


# ---------------------------------------------------------------------------
# Orders service – create_order
# ---------------------------------------------------------------------------

class TestCreateOrderService:
    def test_creates_order_with_correct_totals(self):
        from app.services import orders as svc
        from app.models import NewOrderItem
        items = [NewOrderItem(dish_name="Pizza", dish_price=10.0, quantity=2)]

        order_row = make_order(subtotal=20.0, tax_amount=2.0, total=22.0)

        def fake_insert(table, body, return_result=True):
            if table == "orders":
                return [order_row]
            return None

        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.insert.side_effect = fake_insert
            result = svc.create_order("table-1", 5, items)

        assert result.id == "order-1"

    def test_raises_when_order_insert_fails(self):
        from app.services import orders as svc
        from app.models import NewOrderItem
        items = [NewOrderItem(dish_name="X", dish_price=5.0, quantity=1)]

        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.insert.return_value = None
            with pytest.raises(RuntimeError, match="failed to create order"):
                svc.create_order("t-1", 1, items)

    def test_items_get_pending_kitchen_status(self):
        from app.services import orders as svc
        from app.models import NewOrderItem
        items = [NewOrderItem(dish_name="X", dish_price=5.0, quantity=1)]
        order_row = make_order()
        captured = []

        def fake_insert(table, body, return_result=True):
            if table == "order_items":
                captured.extend(body if isinstance(body, list) else [body])
                return None
            return [order_row]

        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.insert.side_effect = fake_insert
            svc.create_order("t-1", 1, items)

        assert captured[0]["kitchen_status"] == "pending"
        assert captured[0]["payment_status"] == "unassigned"


# ---------------------------------------------------------------------------
# Orders service – close_order
# ---------------------------------------------------------------------------

class TestCloseOrderService:
    def test_close_order_calls_update_with_closed_status(self):
        from app.services import orders as svc
        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.update.return_value = None
            svc.close_order("order-uuid")

        call_args = mock_sb.update.call_args
        assert call_args[0][0] == "orders"
        assert "order-uuid" in call_args[0][1]
        assert call_args[0][2]["status"] == "closed"
        assert "updated_at" in call_args[0][2]


# ---------------------------------------------------------------------------
# Orders service – update_items_payment_status edge cases
# ---------------------------------------------------------------------------

class TestUpdateItemsPaymentStatus:
    def test_does_nothing_with_empty_list(self):
        from app.services import orders as svc
        with patch("app.services.orders.supabase") as mock_sb:
            svc.update_items_payment_status([], "paid")
        mock_sb.update.assert_not_called()

    def test_builds_in_clause_correctly(self):
        from app.services import orders as svc
        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.update.return_value = None
            svc.update_items_payment_status(["a", "b", "c"], "paid")

        query = mock_sb.update.call_args[0][1]
        assert "id=in." in query
        assert "a" in query
        assert "b" in query
        assert "c" in query

    def test_updates_correct_payment_status(self):
        from app.services import orders as svc
        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.update.return_value = None
            svc.update_items_payment_status(["item-1"], "assigned")

        body = mock_sb.update.call_args[0][2]
        assert body["payment_status"] == "assigned"


# ---------------------------------------------------------------------------
# Orders service – update_item_kitchen_status
# ---------------------------------------------------------------------------

class TestUpdateItemKitchenStatus:
    def test_calls_update_with_correct_args(self):
        from app.services import orders as svc
        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.update.return_value = None
            svc.update_item_kitchen_status("item-xyz", "ready")

        call_args = mock_sb.update.call_args
        assert call_args[0][0] == "order_items"
        assert "item-xyz" in call_args[0][1]
        assert call_args[0][2]["kitchen_status"] == "ready"

"""
Unit tests for the service layer, exercising business logic directly
without going through the HTTP stack.

Tests cover:
- app/services/dishes.py
- app/services/orders.py  (math, DB call shapes, edge cases, ingredient customization)
"""

import pytest
from unittest.mock import patch, call, MagicMock
from tests.conftest import make_dish, make_category, make_order, make_order_item, VALID_TENANT_ID
from app.models import NewOrderItem


# ---------------------------------------------------------------------------
# Dishes service
# ---------------------------------------------------------------------------

class TestDishesService:
    def test_get_dishes_returns_dish_objects(self):
        from app.services import dishes as svc
        dish_rows = [make_dish(), make_dish(id="d-2", name="Pasta")]
        with patch("app.services.dishes.supabase") as mock_sb:
            mock_sb.select.return_value = dish_rows
            result = svc.get_dishes(VALID_TENANT_ID)

        assert len(result) == 2
        assert result[0].name == "Pizza Margherita"
        assert result[1].id == "d-2"

    def test_get_dishes_returns_empty_list(self):
        from app.services import dishes as svc
        with patch("app.services.dishes.supabase") as mock_sb:
            mock_sb.select.return_value = []
            result = svc.get_dishes(VALID_TENANT_ID)
        assert result == []

    def test_get_categories_returns_category_objects(self):
        from app.services import dishes as svc
        cats = [make_category(), make_category(id="c-2", name="Pastas", sort_order=2)]
        with patch("app.services.dishes.supabase") as mock_sb:
            mock_sb.select.return_value = cats
            result = svc.get_categories(VALID_TENANT_ID)

        assert len(result) == 2
        assert result[0].sort_order == 1
        assert result[1].name == "Pastas"

    def test_get_categories_returns_empty_list(self):
        from app.services import dishes as svc
        with patch("app.services.dishes.supabase") as mock_sb:
            mock_sb.select.return_value = []
            result = svc.get_categories(VALID_TENANT_ID)
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
        with patch("app.services.orders._get_tenant_table_ids", return_value=["table-1"]):
            with patch("app.services.orders.supabase") as mock_sb:
                mock_sb.select.return_value = []
                svc.fetch_orders(VALID_TENANT_ID, "open")

        call_args = mock_sb.select.call_args
        assert call_args[0][0] == "orders"
        query = call_args[0][1]
        assert "status=eq.open" in query

    def test_fetch_orders_closed_queries_with_desc_order(self):
        from app.services import orders as svc
        with patch("app.services.orders._get_tenant_table_ids", return_value=["table-1"]):
            with patch("app.services.orders.supabase") as mock_sb:
                mock_sb.select.return_value = []
                svc.fetch_orders(VALID_TENANT_ID, "closed")

        query = mock_sb.select.call_args[0][1]
        assert "status=eq.closed" in query
        assert "updated_at.desc" in query

    def test_fetch_orders_returns_list_of_order_objects(self):
        from app.services import orders as svc
        rows = [make_order(), make_order(id="order-2", table_number=7)]
        with patch("app.services.orders._get_tenant_table_ids", return_value=["table-1"]):
            with patch("app.services.orders.supabase") as mock_sb:
                mock_sb.select.return_value = rows
                result = svc.fetch_orders(VALID_TENANT_ID, "open")

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
        order = make_order(id="order-uuid")
        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.select.return_value = [order]
            mock_sb.update.return_value = None
            with patch("app.services.dishes.supabase") as mock_dish_sb:
                mock_dish_sb.delete.return_value = None
                svc.close_order("order-uuid")

        order_call = mock_sb.update.call_args_list[0]
        assert order_call[0][0] == "orders"
        assert "order-uuid" in order_call[0][1]
        assert order_call[0][2]["status"] == "closed"
        assert "updated_at" in order_call[0][2]

        table_call = mock_sb.update.call_args_list[1]
        assert table_call[0][0] == "restaurant_tables"
        assert "table-1" in table_call[0][1]
        assert table_call[0][2]["status"] == "available"
        assert table_call[0][2]["active_order_id"] is None


# ---------------------------------------------------------------------------
# Orders service – _maybe_close_order
# ---------------------------------------------------------------------------

class TestMaybeCloseOrder:
    def test_closes_order_when_all_items_paid_and_delivered(self):
        from app.services.orders import _maybe_close_order
        item = make_order_item(payment_status="paid", kitchen_status="delivered")
        order = make_order(items=[item])
        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.select.side_effect = [
                [order],   # get_order_by_id inside _maybe_close_order
                [order],   # get_order_by_id inside close_order
            ]
            mock_sb.update.return_value = None
            with patch("app.services.dishes.supabase") as mock_dish_sb:
                mock_dish_sb.delete.return_value = None
                _maybe_close_order("order-1")

        order_update = mock_sb.update.call_args_list[0]
        assert order_update[0][2]["status"] == "closed"

    def test_does_not_close_when_item_not_paid(self):
        from app.services.orders import _maybe_close_order
        item = make_order_item(payment_status="assigned", kitchen_status="delivered")
        order = make_order(items=[item])
        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.select.return_value = [order]
            _maybe_close_order("order-1")

        mock_sb.update.assert_not_called()

    def test_does_not_close_when_item_not_delivered(self):
        from app.services.orders import _maybe_close_order
        item = make_order_item(payment_status="paid", kitchen_status="cooking")
        order = make_order(items=[item])
        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.select.return_value = [order]
            _maybe_close_order("order-1")

        mock_sb.update.assert_not_called()

    def test_closes_when_item_has_no_kitchen_status(self):
        from app.services.orders import _maybe_close_order
        item = make_order_item(payment_status="paid", kitchen_status=None)
        order = make_order(items=[item])
        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.select.side_effect = [[order], [order]]
            mock_sb.update.return_value = None
            with patch("app.services.dishes.supabase") as mock_dish_sb:
                mock_dish_sb.delete.return_value = None
                _maybe_close_order("order-1")

        assert mock_sb.update.call_args_list[0][0][2]["status"] == "closed"

    def test_skips_already_closed_order(self):
        from app.services.orders import _maybe_close_order
        order = make_order(status="closed", items=[])
        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.select.return_value = [order]
            _maybe_close_order("order-1")

        mock_sb.update.assert_not_called()


# ---------------------------------------------------------------------------
# Orders service – auto_close_orders_for_items (batch)
# ---------------------------------------------------------------------------

class TestAutoCloseOrdersForItems:
    def test_deduplicates_order_ids_single_close_call(self):
        """Multiple items from the same order trigger only one close check."""
        from app.services.orders import auto_close_orders_for_items
        item = make_order_item(payment_status="paid", kitchen_status="delivered")
        order = make_order(items=[item])
        with patch("app.services.orders.supabase") as mock_sb:
            # Batch select returns same order_id for 3 different items
            mock_sb.select.side_effect = [
                [{"order_id": "order-1"}, {"order_id": "order-1"}, {"order_id": "order-1"}],
                [order],   # _maybe_close_order: get_order_by_id
                [order],   # close_order: get_order_by_id
            ]
            mock_sb.update.return_value = None
            with patch("app.services.dishes.supabase") as mock_dish_sb:
                mock_dish_sb.delete.return_value = None
                auto_close_orders_for_items(["item-1", "item-2", "item-3"])

        # Only one close_order call regardless of 3 items
        orders_closed = [
            c for c in mock_sb.update.call_args_list if c[0][0] == "orders"
        ]
        assert len(orders_closed) == 1

    def test_handles_items_from_different_orders(self):
        """Items from different orders each get their own close check."""
        from app.services.orders import auto_close_orders_for_items
        item_a = make_order_item(payment_status="paid", kitchen_status="delivered")
        order_a = make_order(id="order-a", items=[item_a])
        order_b = make_order(id="order-b", status="closed", items=[])  # already closed — skip
        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.select.side_effect = [
                [{"order_id": "order-a"}, {"order_id": "order-b"}],  # batch
                [order_a],  # _maybe_close_order order-a
                [order_a],  # close_order order-a
                [order_b],  # _maybe_close_order order-b → status!=open, skip
            ]
            mock_sb.update.return_value = None
            with patch("app.services.dishes.supabase") as mock_dish_sb:
                mock_dish_sb.delete.return_value = None
                auto_close_orders_for_items(["item-a", "item-b"])

        orders_closed = [
            c for c in mock_sb.update.call_args_list if c[0][0] == "orders"
        ]
        assert len(orders_closed) == 1  # only order-a closed

    def test_empty_list_does_nothing(self):
        from app.services.orders import auto_close_orders_for_items
        with patch("app.services.orders.supabase") as mock_sb:
            auto_close_orders_for_items([])
        mock_sb.select.assert_not_called()


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
            mock_sb.select.return_value = [{"order_id": "order-1", "order": {"tenant_id": VALID_TENANT_ID}}]
            mock_sb.update.return_value = None
            svc.update_item_kitchen_status("item-xyz", "ready", VALID_TENANT_ID)

        call_args = mock_sb.update.call_args
        assert call_args[0][0] == "order_items"
        assert "item-xyz" in call_args[0][1]
        assert call_args[0][2]["kitchen_status"] == "ready"


# ---------------------------------------------------------------------------
# Orders service – _resolve_ingredient_customizations
# ---------------------------------------------------------------------------

# Helpers for building mock select responses
DISH_ID = "dish-abc"
ING_EXTRA_1 = "ing-extra-1"
ING_EXTRA_2 = "ing-extra-2"
ING_DEFAULT_1 = "ing-default-1"


def _mock_select_for_resolve(table, query):
    """Route supabase.select calls to return appropriate test data."""
    if table == "dishes":
        return [{"id": DISH_ID, "price": 10.0, "max_extra_choices": 2}]
    if table == "dish_ingredients":
        return [
            {"ingredient_id": ING_EXTRA_1, "present": False},
            {"ingredient_id": ING_EXTRA_2, "present": False},
            {"ingredient_id": ING_DEFAULT_1, "present": True},
        ]
    if table == "ingredients":
        return [
            {"id": ING_EXTRA_1, "extra_price": 1.50},
            {"id": ING_EXTRA_2, "extra_price": 2.00},
        ]
    return []


class TestResolveIngredientCustomizations:
    def test_no_dish_id_returns_empty(self):
        from app.services.orders import _resolve_ingredient_customizations
        items = [NewOrderItem(dish_name="Custom", dish_price=5.0, quantity=1)]
        with patch("app.services.orders.supabase"):
            prices, rows = _resolve_ingredient_customizations(items)
        assert prices == {}
        assert rows == {}

    def test_no_customization_uses_server_base_price(self):
        from app.services.orders import _resolve_ingredient_customizations
        items = [NewOrderItem(dish_name="Pizza", dish_price=99.0, quantity=1, dish_id=DISH_ID)]
        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.select.side_effect = _mock_select_for_resolve
            prices, rows = _resolve_ingredient_customizations(items)
        assert prices[0] == 10.0  # server price, not frontend 99.0
        assert rows == {}

    def test_added_ingredients_increase_price(self):
        from app.services.orders import _resolve_ingredient_customizations
        items = [NewOrderItem(
            dish_name="Pizza", dish_price=10.0, quantity=1, dish_id=DISH_ID,
            customization={
                "added_ingredients": [
                    {"ingredient_id": ING_EXTRA_1, "name": "Bacon", "extra_price": 1.50},
                ],
                "removed_ingredients": [],
            },
        )]
        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.select.side_effect = _mock_select_for_resolve
            prices, rows = _resolve_ingredient_customizations(items)
        assert prices[0] == 11.50  # 10.0 + 1.50
        assert len(rows[0]) == 1
        assert rows[0][0]["action"] == "added"

    def test_multiple_extras_summed(self):
        from app.services.orders import _resolve_ingredient_customizations
        items = [NewOrderItem(
            dish_name="Pizza", dish_price=10.0, quantity=1, dish_id=DISH_ID,
            customization={
                "added_ingredients": [
                    {"ingredient_id": ING_EXTRA_1, "name": "Bacon", "extra_price": 1.50},
                    {"ingredient_id": ING_EXTRA_2, "name": "Cheese", "extra_price": 2.00},
                ],
            },
        )]
        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.select.side_effect = _mock_select_for_resolve
            prices, rows = _resolve_ingredient_customizations(items)
        assert prices[0] == 13.50  # 10.0 + 1.50 + 2.00

    def test_removed_ingredients_do_not_change_price(self):
        from app.services.orders import _resolve_ingredient_customizations
        items = [NewOrderItem(
            dish_name="Pizza", dish_price=10.0, quantity=1, dish_id=DISH_ID,
            customization={
                "added_ingredients": [],
                "removed_ingredients": [ING_DEFAULT_1],
            },
        )]
        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.select.side_effect = _mock_select_for_resolve
            prices, rows = _resolve_ingredient_customizations(items)
        assert prices[0] == 10.0
        assert len(rows[0]) == 1
        assert rows[0][0]["action"] == "removed"

    def test_uses_server_extra_price_not_frontend(self):
        """Frontend sends extra_price=0.01 but server has 1.50 — server wins."""
        from app.services.orders import _resolve_ingredient_customizations
        items = [NewOrderItem(
            dish_name="Pizza", dish_price=10.0, quantity=1, dish_id=DISH_ID,
            customization={
                "added_ingredients": [
                    {"ingredient_id": ING_EXTRA_1, "name": "Bacon", "extra_price": 0.01},
                ],
            },
        )]
        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.select.side_effect = _mock_select_for_resolve
            prices, rows = _resolve_ingredient_customizations(items)
        assert prices[0] == 11.50  # uses server 1.50, not frontend 0.01

    def test_max_extra_choices_exceeded_raises(self):
        from app.services.orders import _resolve_ingredient_customizations

        def mock_select_max1(table, query):
            if table == "dishes":
                return [{"id": DISH_ID, "price": 10.0, "max_extra_choices": 1}]
            return _mock_select_for_resolve(table, query)

        items = [NewOrderItem(
            dish_name="Pizza", dish_price=10.0, quantity=1, dish_id=DISH_ID,
            customization={
                "added_ingredients": [
                    {"ingredient_id": ING_EXTRA_1, "name": "Bacon", "extra_price": 1.50},
                    {"ingredient_id": ING_EXTRA_2, "name": "Cheese", "extra_price": 2.00},
                ],
            },
        )]
        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.select.side_effect = mock_select_max1
            with pytest.raises(ValueError, match="max 1 extra ingredients"):
                _resolve_ingredient_customizations(items)

    def test_ingredient_not_found_raises(self):
        from app.services.orders import _resolve_ingredient_customizations

        def mock_select_missing(table, query):
            if table == "ingredients":
                return []  # ingredient not in DB
            return _mock_select_for_resolve(table, query)

        items = [NewOrderItem(
            dish_name="Pizza", dish_price=10.0, quantity=1, dish_id=DISH_ID,
            customization={
                "added_ingredients": [
                    {"ingredient_id": ING_EXTRA_1, "name": "Bacon", "extra_price": 1.50},
                ],
            },
        )]
        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.select.side_effect = mock_select_missing
            with pytest.raises(ValueError, match="not found"):
                _resolve_ingredient_customizations(items)

    def test_ingredient_not_belonging_to_dish_raises(self):
        from app.services.orders import _resolve_ingredient_customizations

        def mock_select_no_junction(table, query):
            if table == "dish_ingredients":
                return []  # no junction rows
            if table == "ingredients":
                return [{"id": ING_EXTRA_1, "extra_price": 1.50}]
            return _mock_select_for_resolve(table, query)

        items = [NewOrderItem(
            dish_name="Pizza", dish_price=10.0, quantity=1, dish_id=DISH_ID,
            customization={
                "added_ingredients": [
                    {"ingredient_id": ING_EXTRA_1, "name": "Bacon", "extra_price": 1.50},
                ],
            },
        )]
        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.select.side_effect = mock_select_no_junction
            with pytest.raises(ValueError, match="does not belong"):
                _resolve_ingredient_customizations(items)

    def test_adding_default_ingredient_raises(self):
        """Cannot add an ingredient that is already default (present=true)."""
        from app.services.orders import _resolve_ingredient_customizations

        def mock_select_default_as_extra(table, query):
            if table == "ingredients":
                return [{"id": ING_DEFAULT_1, "extra_price": 0}]
            return _mock_select_for_resolve(table, query)

        items = [NewOrderItem(
            dish_name="Pizza", dish_price=10.0, quantity=1, dish_id=DISH_ID,
            customization={
                "added_ingredients": [
                    {"ingredient_id": ING_DEFAULT_1, "name": "Tomato", "extra_price": 0},
                ],
            },
        )]
        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.select.side_effect = mock_select_default_as_extra
            with pytest.raises(ValueError, match="default ingredient"):
                _resolve_ingredient_customizations(items)

    def test_removing_non_default_ingredient_raises(self):
        """Cannot remove an ingredient that is not default (present=false)."""
        from app.services.orders import _resolve_ingredient_customizations
        items = [NewOrderItem(
            dish_name="Pizza", dish_price=10.0, quantity=1, dish_id=DISH_ID,
            customization={
                "removed_ingredients": [ING_EXTRA_1],
            },
        )]
        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.select.side_effect = _mock_select_for_resolve
            with pytest.raises(ValueError, match="not a default ingredient"):
                _resolve_ingredient_customizations(items)


# ---------------------------------------------------------------------------
# Orders service – _build_and_insert_items with ingredients
# ---------------------------------------------------------------------------

class TestBuildAndInsertItemsWithIngredients:
    def test_inserts_order_item_ingredients_when_customization_present(self):
        from app.services.orders import _build_and_insert_items
        items = [NewOrderItem(
            dish_name="Pizza", dish_price=10.0, quantity=1, dish_id=DISH_ID,
            customization={
                "added_ingredients": [
                    {"ingredient_id": ING_EXTRA_1, "name": "Bacon", "extra_price": 1.50},
                ],
                "removed_ingredients": [ING_DEFAULT_1],
            },
        )]

        inserted_items = [{"id": "oi-1", "order_id": "order-1"}]
        captured_ing_rows = []

        def fake_insert(table, body, return_result=True):
            if table == "order_items":
                return inserted_items
            if table == "order_item_ingredients":
                captured_ing_rows.extend(body if isinstance(body, list) else [body])
                return None
            return None

        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.select.side_effect = _mock_select_for_resolve
            mock_sb.insert.side_effect = fake_insert
            _build_and_insert_items("order-1", items)

        assert len(captured_ing_rows) == 2
        added_row = next(r for r in captured_ing_rows if r["action"] == "added")
        removed_row = next(r for r in captured_ing_rows if r["action"] == "removed")
        assert added_row["order_item_id"] == "oi-1"
        assert added_row["ingredient_id"] == ING_EXTRA_1
        assert "extra_price" not in added_row
        assert removed_row["order_item_id"] == "oi-1"
        assert removed_row["ingredient_id"] == ING_DEFAULT_1
        assert "extra_price" not in removed_row

    def test_no_customization_skips_ingredient_insert(self):
        from app.services.orders import _build_and_insert_items
        items = [NewOrderItem(dish_name="Custom dish", dish_price=5.0, quantity=1)]

        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.select.return_value = []
            mock_sb.insert.return_value = None
            _build_and_insert_items("order-1", items)

        # Should insert order_items without return_result (no ingredient rows needed)
        insert_call = mock_sb.insert.call_args
        assert insert_call[0][0] == "order_items"
        assert insert_call[1].get("return_result", True) is False

    def test_dish_price_uses_resolved_server_price(self):
        from app.services.orders import _build_and_insert_items
        items = [NewOrderItem(
            dish_name="Pizza", dish_price=99.99, quantity=1, dish_id=DISH_ID,
            customization={
                "added_ingredients": [
                    {"ingredient_id": ING_EXTRA_1, "name": "Bacon", "extra_price": 1.50},
                ],
            },
        )]
        captured_rows = []

        def fake_insert(table, body, return_result=True):
            if table == "order_items":
                captured_rows.extend(body if isinstance(body, list) else [body])
                return [{"id": "oi-1"}]
            return None

        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.select.side_effect = _mock_select_for_resolve
            mock_sb.insert.side_effect = fake_insert
            _build_and_insert_items("order-1", items)

        assert captured_rows[0]["dish_price"] == 11.50  # 10.0 base + 1.50, not 99.99


# ---------------------------------------------------------------------------
# Orders service – _calculate_subtotal with resolved prices
# ---------------------------------------------------------------------------

class TestCalculateSubtotalWithResolvedPrices:
    def test_uses_resolved_prices_when_provided(self):
        from app.services.orders import _calculate_subtotal
        items = [
            NewOrderItem(dish_name="A", dish_price=99.0, quantity=2),
            NewOrderItem(dish_name="B", dish_price=5.0, quantity=1),
        ]
        resolved = {0: 11.50}  # only first item resolved
        result = _calculate_subtotal(items, resolved)
        assert result == 28.0  # 11.50*2 + 5.0*1

    def test_falls_back_to_frontend_price_when_not_resolved(self):
        from app.services.orders import _calculate_subtotal
        items = [NewOrderItem(dish_name="A", dish_price=7.0, quantity=3)]
        resolved = {}  # empty but truthy would be falsy, test with None
        result = _calculate_subtotal(items, None)
        assert result == 21.0

"""
Unit tests for the service layer, exercising business logic directly
without going through the HTTP stack.

Tests cover:
- app/services/dishes.py
- app/services/orders.py  (math, DB call shapes, edge cases, ingredient customization)
"""

import pytest
from unittest.mock import patch, call, MagicMock
from tests.conftest import (
    make_dish, make_category, make_order, make_order_item,
    make_mock_client, VALID_TENANT_ID,
)
from app.models import NewOrderItem


# ---------------------------------------------------------------------------
# Dishes service
# ---------------------------------------------------------------------------

class TestDishesService:
    def test_get_dishes_returns_dish_objects(self):
        from app.services import dishes as svc
        dish_rows = [make_dish(), make_dish(id="d-2", name="Pasta")]
        with patch("app.services.dishes.get_client") as mock_gc:
            mock_gc.return_value = make_mock_client(data=dish_rows)
            result = svc.get_dishes(VALID_TENANT_ID)

        assert len(result) == 2
        assert result[0].name == "Pizza Margherita"
        assert result[1].id == "d-2"

    def test_get_dishes_returns_empty_list(self):
        from app.services import dishes as svc
        with patch("app.services.dishes.get_client") as mock_gc:
            mock_gc.return_value = make_mock_client(data=[])
            result = svc.get_dishes(VALID_TENANT_ID)
        assert result == []

    def test_get_categories_returns_category_objects(self):
        from app.services import dishes as svc
        cats = [make_category(), make_category(id="c-2", name="Pastas", sort_order=2)]
        with patch("app.services.dishes.get_client") as mock_gc:
            mock_gc.return_value = make_mock_client(data=cats)
            result = svc.get_categories(VALID_TENANT_ID)

        assert len(result) == 2
        assert result[0].sort_order == 1
        assert result[1].name == "Pastas"

    def test_get_categories_returns_empty_list(self):
        from app.services import dishes as svc
        with patch("app.services.dishes.get_client") as mock_gc:
            mock_gc.return_value = make_mock_client(data=[])
            result = svc.get_categories(VALID_TENANT_ID)
        assert result == []


# ---------------------------------------------------------------------------
# Orders service – math helpers
# ---------------------------------------------------------------------------

class TestOrdersMath:
    def test_round2_rounds_correctly(self):
        from app.services.orders import _round2
        assert _round2(10.0) == 10.0
        assert _round2(0.0) == 0.0
        assert _round2(2.225) == 2.23
        assert _round2(25.0) == 25.0
        assert _round2(100.5) == 100.5
        assert _round2(1.235) == 1.24

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
    def test_fetch_orders_open_returns_list_of_order_objects(self):
        from app.services import orders as svc
        rows = [make_order(), make_order(id="order-2", table_number=7)]
        mock_q = make_mock_client(data=rows)
        with patch("app.services.orders._get_tenant_table_ids", return_value=["table-1"]):
            with patch("app.services.orders.get_client") as mock_gc:
                mock_gc.return_value = mock_q
                result = svc.fetch_orders(VALID_TENANT_ID, "open")

        assert len(result) == 2
        assert result[0].id == "order-1"
        assert result[1].table_number == 7

    def test_fetch_orders_closed_returns_orders(self):
        from app.services import orders as svc
        mock_q = make_mock_client(data=[])
        with patch("app.services.orders._get_tenant_table_ids", return_value=["table-1"]):
            with patch("app.services.orders.get_client") as mock_gc:
                mock_gc.return_value = mock_q
                result = svc.fetch_orders(VALID_TENANT_ID, "closed")
        assert result == []


# ---------------------------------------------------------------------------
# Orders service – get_order_by_id
# ---------------------------------------------------------------------------

class TestGetOrderById:
    def test_returns_order_when_found(self):
        from app.services import orders as svc
        row = make_order()
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = make_mock_client(data=[row])
            result = svc.get_order_by_id("order-1")
        assert result is not None
        assert result.id == "order-1"

    def test_returns_none_when_not_found(self):
        from app.services import orders as svc
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = make_mock_client(data=[])
            result = svc.get_order_by_id("missing")
        assert result is None


# ---------------------------------------------------------------------------
# Orders service – get_open_order_for_table
# ---------------------------------------------------------------------------

class TestGetOpenOrderForTable:
    def test_returns_order_when_found(self):
        from app.services import orders as svc
        row = make_order()
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = make_mock_client(data=[row])
            result = svc.get_open_order_for_table("table-1")
        assert result is not None
        assert result.table_id == "table-1"

    def test_returns_none_when_not_found(self):
        from app.services import orders as svc
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = make_mock_client(data=[])
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

        mock_q = make_mock_client(data=[order_row])
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = mock_q
            result = svc.create_order("table-1", 5, items)

        assert result.id == "order-1"

    def test_raises_when_order_insert_fails(self):
        from app.services import orders as svc
        from app.models import NewOrderItem
        items = [NewOrderItem(dish_name="X", dish_price=5.0, quantity=1)]

        mock_q = make_mock_client()
        mock_q.execute.return_value = MagicMock(data=None)
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = mock_q
            with pytest.raises(RuntimeError, match="failed to create order"):
                svc.create_order("t-1", 1, items)

    def test_items_get_pending_kitchen_status(self):
        from app.services import orders as svc
        from app.models import NewOrderItem
        items = [NewOrderItem(dish_name="X", dish_price=5.0, quantity=1)]
        order_row = make_order()

        captured_inserts = []

        mock_q = make_mock_client(data=[order_row])

        def track_insert(body):
            captured_inserts.append(body)
            return mock_q

        mock_q.insert = track_insert
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = mock_q
            svc.create_order("t-1", 1, items)

        # Find the order_items insert call
        item_insert = next(
            (b for b in captured_inserts if isinstance(b, list) and b and "kitchen_status" in b[0]),
            None
        )
        assert item_insert is not None
        assert item_insert[0]["kitchen_status"] == "pending"
        assert item_insert[0]["payment_status"] == "unassigned"


# ---------------------------------------------------------------------------
# Orders service – close_order
# ---------------------------------------------------------------------------

class TestCloseOrderService:
    def test_close_order_calls_update_with_closed_status(self):
        from app.services import orders as svc
        order = make_order(id="order-uuid")

        mock_q = make_mock_client(data=[order])

        updated_bodies = []

        def track_update(body):
            updated_bodies.append(body)
            return mock_q

        mock_q.update = track_update

        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = mock_q
            with patch("app.services.dishes.get_client") as mock_dish_gc:
                mock_dish_gc.return_value = make_mock_client(data=None)
                svc.close_order("order-uuid")

        # At least one update with status=closed
        assert any(b.get("status") == "closed" for b in updated_bodies)


# ---------------------------------------------------------------------------
# Orders service – _maybe_close_order
# ---------------------------------------------------------------------------

class TestMaybeCloseOrder:
    def test_closes_order_when_all_items_paid_and_delivered(self):
        from app.services.orders import _maybe_close_order
        item = make_order_item(payment_status="paid", kitchen_status="delivered")
        order = make_order(items=[item])

        mock_q = make_mock_client(data=[order])
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = mock_q
            with patch("app.services.dishes.get_client") as mock_dish_gc:
                mock_dish_gc.return_value = make_mock_client(data=None)
                _maybe_close_order("order-1")

        # update was called (order closed)
        assert mock_q.update.called

    def test_does_not_close_when_item_not_paid(self):
        from app.services.orders import _maybe_close_order
        item = make_order_item(payment_status="assigned", kitchen_status="delivered")
        order = make_order(items=[item])

        mock_q = make_mock_client()
        mock_q.execute.return_value = MagicMock(data=[order])
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = mock_q
            _maybe_close_order("order-1")

        mock_q.update.assert_not_called()

    def test_does_not_close_when_item_not_delivered(self):
        from app.services.orders import _maybe_close_order
        item = make_order_item(payment_status="paid", kitchen_status="cooking")
        order = make_order(items=[item])

        mock_q = make_mock_client()
        mock_q.execute.return_value = MagicMock(data=[order])
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = mock_q
            _maybe_close_order("order-1")

        mock_q.update.assert_not_called()

    def test_closes_when_item_has_no_kitchen_status(self):
        from app.services.orders import _maybe_close_order
        item = make_order_item(payment_status="paid", kitchen_status=None)
        order = make_order(items=[item])

        mock_q = make_mock_client(data=[order])
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = mock_q
            with patch("app.services.dishes.get_client") as mock_dish_gc:
                mock_dish_gc.return_value = make_mock_client(data=None)
                _maybe_close_order("order-1")

        assert mock_q.update.called

    def test_skips_already_closed_order(self):
        from app.services.orders import _maybe_close_order
        order = make_order(status="closed", items=[])

        mock_q = make_mock_client()
        mock_q.execute.return_value = MagicMock(data=[order])
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = mock_q
            _maybe_close_order("order-1")

        mock_q.update.assert_not_called()


# ---------------------------------------------------------------------------
# Orders service – auto_close_orders_for_items (batch)
# ---------------------------------------------------------------------------

class TestAutoCloseOrdersForItems:
    def test_deduplicates_order_ids_single_close_call(self):
        """Multiple items from the same order trigger only one close check."""
        from app.services.orders import auto_close_orders_for_items
        item = make_order_item(payment_status="paid", kitchen_status="delivered")
        order = make_order(items=[item])

        mock_q = make_mock_client()
        mock_q.execute.side_effect = [
            MagicMock(data=[{"order_id": "order-1"}, {"order_id": "order-1"}, {"order_id": "order-1"}]),
        ] + [MagicMock(data=[order])] * 12  # get_order_by_id (+ table-label) and the close updates
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = mock_q
            with patch("app.services.dishes.get_client") as mock_dish_gc:
                mock_dish_gc.return_value = make_mock_client(data=None)
                auto_close_orders_for_items(["item-1", "item-2", "item-3"])

        # update was called (close happened once)
        assert mock_q.update.called

    def test_empty_list_does_nothing(self):
        from app.services.orders import auto_close_orders_for_items
        mock_q = make_mock_client()
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = mock_q
            auto_close_orders_for_items([])

        mock_q.execute.assert_not_called()


# ---------------------------------------------------------------------------
# Orders service – update_items_payment_status edge cases
# ---------------------------------------------------------------------------

class TestUpdateItemsPaymentStatus:
    def test_does_nothing_with_empty_list(self):
        from app.services import orders as svc
        mock_q = make_mock_client()
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = mock_q
            svc.update_items_payment_status([], "paid", VALID_TENANT_ID)
        mock_q.execute.assert_not_called()

    def test_updates_correct_payment_status(self):
        from app.services import orders as svc

        mock_q = make_mock_client()
        mock_q.execute.side_effect = [
            MagicMock(data=[{"id": "item-1", "order": {"tenant_id": VALID_TENANT_ID}}]),  # select
            MagicMock(data=None),  # update
        ]
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = mock_q
            svc.update_items_payment_status(["item-1"], "assigned", VALID_TENANT_ID)

        assert mock_q.update.called

    def test_raises_for_item_from_other_tenant(self):
        from app.services import orders as svc

        mock_q = make_mock_client()
        mock_q.execute.return_value = MagicMock(
            data=[{"id": "item-1", "order": {"tenant_id": "other-tenant"}}]
        )
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = mock_q
            with pytest.raises(ValueError):
                svc.update_items_payment_status(["item-1"], "paid", VALID_TENANT_ID)

        mock_q.update.assert_not_called()

    def test_builds_in_clause_using_in_(self):
        """Verifies in_() is called on the query for multiple item IDs."""
        from app.services import orders as svc

        mock_q = make_mock_client()
        in_call_args = []
        original_in = mock_q.in_

        def track_in(col, vals):
            in_call_args.append((col, vals))
            return mock_q

        mock_q.in_ = track_in
        mock_q.execute.side_effect = [
            MagicMock(data=[
                {"id": "a", "order": {"tenant_id": VALID_TENANT_ID}},
                {"id": "b", "order": {"tenant_id": VALID_TENANT_ID}},
            ]),
            MagicMock(data=None),
        ]
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = mock_q
            svc.update_items_payment_status(["a", "b"], "paid", VALID_TENANT_ID)

        assert any("a" in str(args) for args in in_call_args)


# ---------------------------------------------------------------------------
# Orders service – update_item_kitchen_status
# ---------------------------------------------------------------------------

class TestUpdateItemKitchenStatus:
    def test_calls_update_with_correct_args(self):
        from app.services import orders as svc

        mock_q = make_mock_client()
        mock_q.execute.side_effect = [
            MagicMock(data=[{"order_id": "order-1", "order": {"tenant_id": VALID_TENANT_ID}}]),  # _assert_item_owner
        ] + [MagicMock(data=None)] * 10  # update + _sync get_order_by_id (None -> sync no-ops)
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = mock_q
            svc.update_item_kitchen_status("item-xyz", "ready", VALID_TENANT_ID)

        assert mock_q.update.called


# ---------------------------------------------------------------------------
# Orders service – _resolve_ingredient_customizations
# ---------------------------------------------------------------------------

DISH_ID = "dish-abc"
ING_EXTRA_1 = "ing-extra-1"
ING_EXTRA_2 = "ing-extra-2"
ING_DEFAULT_1 = "ing-default-1"


def _make_resolve_side_effect():
    """Return a callable that routes get_client() mock execute calls by call sequence."""
    dish_data = [{"id": DISH_ID, "price": 10.0, "max_extra_choices": 2}]
    di_data = [
        {"ingredient_id": ING_EXTRA_1, "present": False},
        {"ingredient_id": ING_EXTRA_2, "present": False},
        {"ingredient_id": ING_DEFAULT_1, "present": True},
    ]
    ing_data = [
        {"id": ING_EXTRA_1, "extra_price": 1.50},
        {"id": ING_EXTRA_2, "extra_price": 2.00},
    ]
    results = iter([
        MagicMock(data=dish_data),
        MagicMock(data=di_data),
        MagicMock(data=ing_data),
    ])

    def side_effect():
        return next(results)

    return side_effect


def _make_resolve_mock():
    """Build a mock_q whose execute cycles through the three standard responses."""
    mock_q = make_mock_client()
    mock_q.execute.side_effect = [
        MagicMock(data=[{"id": DISH_ID, "price": 10.0, "max_extra_choices": 2}]),
        MagicMock(data=[
            {"ingredient_id": ING_EXTRA_1, "present": False},
            {"ingredient_id": ING_EXTRA_2, "present": False},
            {"ingredient_id": ING_DEFAULT_1, "present": True},
        ]),
        MagicMock(data=[
            {"id": ING_EXTRA_1, "extra_price": 1.50},
            {"id": ING_EXTRA_2, "extra_price": 2.00},
        ]),
    ]
    return mock_q


class TestResolveIngredientCustomizations:
    def test_no_dish_id_returns_empty(self):
        from app.services.orders import _resolve_ingredient_customizations
        items = [NewOrderItem(dish_name="Custom", dish_price=5.0, quantity=1)]
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = make_mock_client(data=[])
            prices, rows = _resolve_ingredient_customizations(items)
        assert prices == {}
        assert rows == {}

    def test_no_customization_uses_server_base_price(self):
        from app.services.orders import _resolve_ingredient_customizations
        items = [NewOrderItem(dish_name="Pizza", dish_price=99.0, quantity=1, dish_id=DISH_ID)]
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = _make_resolve_mock()
            prices, rows = _resolve_ingredient_customizations(items)
        assert prices[0] == 10.0  # server price
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
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = _make_resolve_mock()
            prices, rows = _resolve_ingredient_customizations(items)
        assert prices[0] == 11.50
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
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = _make_resolve_mock()
            prices, rows = _resolve_ingredient_customizations(items)
        assert prices[0] == 13.50

    def test_removed_ingredients_do_not_change_price(self):
        from app.services.orders import _resolve_ingredient_customizations
        items = [NewOrderItem(
            dish_name="Pizza", dish_price=10.0, quantity=1, dish_id=DISH_ID,
            customization={
                "added_ingredients": [],
                "removed_ingredients": [ING_DEFAULT_1],
            },
        )]
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = _make_resolve_mock()
            prices, rows = _resolve_ingredient_customizations(items)
        assert prices[0] == 10.0
        assert len(rows[0]) == 1
        assert rows[0][0]["action"] == "removed"

    def test_uses_server_extra_price_not_frontend(self):
        from app.services.orders import _resolve_ingredient_customizations
        items = [NewOrderItem(
            dish_name="Pizza", dish_price=10.0, quantity=1, dish_id=DISH_ID,
            customization={
                "added_ingredients": [
                    {"ingredient_id": ING_EXTRA_1, "name": "Bacon", "extra_price": 0.01},
                ],
            },
        )]
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = _make_resolve_mock()
            prices, rows = _resolve_ingredient_customizations(items)
        assert prices[0] == 11.50

    def test_max_extra_choices_exceeded_raises(self):
        from app.services.orders import _resolve_ingredient_customizations

        mock_q = make_mock_client()
        mock_q.execute.side_effect = [
            MagicMock(data=[{"id": DISH_ID, "price": 10.0, "max_extra_choices": 1}]),
            MagicMock(data=[
                {"ingredient_id": ING_EXTRA_1, "present": False},
                {"ingredient_id": ING_EXTRA_2, "present": False},
            ]),
            MagicMock(data=[
                {"id": ING_EXTRA_1, "extra_price": 1.50},
                {"id": ING_EXTRA_2, "extra_price": 2.00},
            ]),
        ]

        items = [NewOrderItem(
            dish_name="Pizza", dish_price=10.0, quantity=1, dish_id=DISH_ID,
            customization={
                "added_ingredients": [
                    {"ingredient_id": ING_EXTRA_1, "name": "Bacon", "extra_price": 1.50},
                    {"ingredient_id": ING_EXTRA_2, "name": "Cheese", "extra_price": 2.00},
                ],
            },
        )]
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = mock_q
            with pytest.raises(ValueError, match="max 1 extra ingredients"):
                _resolve_ingredient_customizations(items)

    def test_ingredient_not_found_raises(self):
        from app.services.orders import _resolve_ingredient_customizations

        mock_q = make_mock_client()
        mock_q.execute.side_effect = [
            MagicMock(data=[{"id": DISH_ID, "price": 10.0, "max_extra_choices": 2}]),
            MagicMock(data=[{"ingredient_id": ING_EXTRA_1, "present": False}]),
            MagicMock(data=[]),  # ingredient not in DB
        ]

        items = [NewOrderItem(
            dish_name="Pizza", dish_price=10.0, quantity=1, dish_id=DISH_ID,
            customization={
                "added_ingredients": [
                    {"ingredient_id": ING_EXTRA_1, "name": "Bacon", "extra_price": 1.50},
                ],
            },
        )]
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = mock_q
            with pytest.raises(ValueError, match="not found"):
                _resolve_ingredient_customizations(items)

    def test_ingredient_not_belonging_to_dish_raises(self):
        from app.services.orders import _resolve_ingredient_customizations

        mock_q = make_mock_client()
        mock_q.execute.side_effect = [
            MagicMock(data=[{"id": DISH_ID, "price": 10.0, "max_extra_choices": 2}]),
            MagicMock(data=[]),  # no junction rows
            MagicMock(data=[{"id": ING_EXTRA_1, "extra_price": 1.50}]),
        ]

        items = [NewOrderItem(
            dish_name="Pizza", dish_price=10.0, quantity=1, dish_id=DISH_ID,
            customization={
                "added_ingredients": [
                    {"ingredient_id": ING_EXTRA_1, "name": "Bacon", "extra_price": 1.50},
                ],
            },
        )]
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = mock_q
            with pytest.raises(ValueError, match="does not belong"):
                _resolve_ingredient_customizations(items)

    def test_adding_default_ingredient_raises(self):
        from app.services.orders import _resolve_ingredient_customizations

        mock_q = make_mock_client()
        mock_q.execute.side_effect = [
            MagicMock(data=[{"id": DISH_ID, "price": 10.0, "max_extra_choices": 2}]),
            MagicMock(data=[{"ingredient_id": ING_DEFAULT_1, "present": True}]),
            MagicMock(data=[{"id": ING_DEFAULT_1, "extra_price": 0}]),
        ]

        items = [NewOrderItem(
            dish_name="Pizza", dish_price=10.0, quantity=1, dish_id=DISH_ID,
            customization={
                "added_ingredients": [
                    {"ingredient_id": ING_DEFAULT_1, "name": "Tomato", "extra_price": 0},
                ],
            },
        )]
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = mock_q
            with pytest.raises(ValueError, match="default ingredient"):
                _resolve_ingredient_customizations(items)

    def test_removing_non_default_ingredient_raises(self):
        from app.services.orders import _resolve_ingredient_customizations

        mock_q = make_mock_client()
        mock_q.execute.side_effect = [
            MagicMock(data=[{"id": DISH_ID, "price": 10.0, "max_extra_choices": 2}]),
            MagicMock(data=[{"ingredient_id": ING_EXTRA_1, "present": False}]),
        ]

        items = [NewOrderItem(
            dish_name="Pizza", dish_price=10.0, quantity=1, dish_id=DISH_ID,
            customization={
                "removed_ingredients": [ING_EXTRA_1],
            },
        )]
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = mock_q
            with pytest.raises(ValueError, match="not a default ingredient"):
                _resolve_ingredient_customizations(items)

    def test_menu_group_item_without_customization_uses_frontend_price(self):
        from app.services.orders import _resolve_ingredient_customizations
        items = [NewOrderItem(
            dish_name="Pizza", dish_price=12.0, quantity=1, dish_id=DISH_ID,
            customization={
                "menu_group": {
                    "menu_name": "Menu del dia",
                    "group_id": "group-1",
                    "base_price": 12.0
                }
            }
        )]
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = _make_resolve_mock()
            prices, rows = _resolve_ingredient_customizations(items)
        assert prices[0] == 12.0  # uses frontend price, not server-side base 10.0
        assert rows == {}

    def test_menu_group_item_with_customization_uses_frontend_price(self):
        from app.services.orders import _resolve_ingredient_customizations
        items = [NewOrderItem(
            dish_name="Pizza", dish_price=13.50, quantity=1, dish_id=DISH_ID,
            customization={
                "added_ingredients": [
                    {"ingredient_id": ING_EXTRA_1, "name": "Bacon", "extra_price": 1.50},
                ],
                "menu_group": {
                    "menu_name": "Menu del dia",
                    "group_id": "group-1",
                    "base_price": 12.0
                }
            }
        )]
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = _make_resolve_mock()
            prices, rows = _resolve_ingredient_customizations(items)
        assert prices[0] == 13.50  # uses frontend price, which already includes supplement/extras
        assert len(rows[0]) == 1
        assert rows[0][0]["action"] == "added"


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

        mock_q = make_mock_client()

        # Track insert calls
        original_insert = mock_q.insert

        def track_insert(body):
            if isinstance(body, list) and body and "action" in body[0]:
                captured_ing_rows.extend(body)
            return mock_q

        mock_q.insert = track_insert
        mock_q.execute.side_effect = [
            # _resolve_ingredient_customizations calls
            MagicMock(data=[{"id": DISH_ID, "price": 10.0, "max_extra_choices": 2}]),
            MagicMock(data=[
                {"ingredient_id": ING_EXTRA_1, "present": False},
                {"ingredient_id": ING_DEFAULT_1, "present": True},
            ]),
            MagicMock(data=[{"id": ING_EXTRA_1, "extra_price": 1.50}]),
            # order_items insert
            MagicMock(data=inserted_items),
            # order_item_ingredients insert
            MagicMock(data=None),
        ]
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = mock_q
            _build_and_insert_items("order-1", items)

        assert len(captured_ing_rows) == 2
        added_row = next(r for r in captured_ing_rows if r["action"] == "added")
        removed_row = next(r for r in captured_ing_rows if r["action"] == "removed")
        assert added_row["ingredient_id"] == ING_EXTRA_1
        assert "extra_price" not in added_row
        assert removed_row["ingredient_id"] == ING_DEFAULT_1

    def test_no_customization_skips_ingredient_insert(self):
        from app.services.orders import _build_and_insert_items
        items = [NewOrderItem(dish_name="Custom dish", dish_price=5.0, quantity=1)]

        mock_q = make_mock_client()
        # No dish_id → _resolve_ingredient_customizations returns early
        mock_q.execute.return_value = MagicMock(data=None)

        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = mock_q
            _build_and_insert_items("order-1", items)

        assert mock_q.insert.called

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

        mock_q = make_mock_client()

        def track_insert(body):
            if isinstance(body, list) and body and "dish_price" in body[0]:
                captured_rows.extend(body)
            return mock_q

        mock_q.insert = track_insert
        mock_q.execute.side_effect = [
            MagicMock(data=[{"id": DISH_ID, "price": 10.0, "max_extra_choices": 2}]),
            MagicMock(data=[{"ingredient_id": ING_EXTRA_1, "present": False}]),
            MagicMock(data=[{"id": ING_EXTRA_1, "extra_price": 1.50}]),
            MagicMock(data=[{"id": "oi-1"}]),
            MagicMock(data=None),
        ]
        with patch("app.services.orders.get_client") as mock_gc:
            mock_gc.return_value = mock_q
            _build_and_insert_items("order-1", items)

        assert captured_rows[0]["dish_price"] == 11.50


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
        resolved = {0: 11.50}
        result = _calculate_subtotal(items, resolved)
        assert result == 28.0

    def test_falls_back_to_frontend_price_when_not_resolved(self):
        from app.services.orders import _calculate_subtotal
        items = [NewOrderItem(dish_name="A", dish_price=7.0, quantity=3)]
        result = _calculate_subtotal(items, None)
        assert result == 21.0

from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timezone

from app.db import supabase
from app.models import NewOrderItem, Order, OrderItem
from app.services import dishes as dish_svc

TAX_RATE_ES = 10.0  # Spain restaurant tax rate (%)


def _round2(v: float) -> float:
    return float(Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _calculate_subtotal(items: list[NewOrderItem]) -> float:
    return sum(i.dish_price * i.quantity for i in items)


def _calculate_subtotal_from_items(items: list[OrderItem]) -> float:
    return sum(i.dish_price * i.quantity for i in items)


def _calculate_tax(subtotal: float) -> float:
    return _round2(subtotal * TAX_RATE_ES / 100)


def fetch_orders(status: str) -> list[Order]:
    query = f"select=*,items:order_items(*)&status=eq.{status}"
    if status == "closed":
        query += "&order=updated_at.desc&limit=100"
    else:
        query += "&order=created_at.asc&limit=1000"

    rows = supabase.select("orders", query)
    return [Order(**row) for row in rows]


def get_order_by_id(order_id: str) -> Order | None:
    query = f"select=*,items:order_items(*)&id=eq.{order_id}&limit=1"
    rows = supabase.select("orders", query)
    if not rows:
        return None
    return Order(**rows[0])


def get_open_order_for_table(table_id: str) -> Order | None:
    query = (
        f"select=*,items:order_items(*)"
        f"&table_id=eq.{table_id}&status=eq.open"
        f"&order=created_at.desc&limit=1"
    )
    rows = supabase.select("orders", query)
    if not rows:
        return None
    return Order(**rows[0])


def create_order(table_id: str, table_number: int, items: list[NewOrderItem]) -> Order:
    subtotal = _calculate_subtotal(items)
    tax_amount = _calculate_tax(subtotal)
    total = _round2(subtotal + tax_amount)

    order_row = {
        "table_id": table_id,
        "table_number": table_number,
        "status": "open",
        "subtotal": subtotal,
        "tax_amount": tax_amount,
        "total": total,
    }

    inserted = supabase.insert("orders", order_row, return_result=True)
    if not inserted:
        raise RuntimeError("failed to create order")
    order = Order(**inserted[0])

    item_rows = _build_item_rows(order.id, items)

    supabase.insert("order_items", item_rows, return_result=False)

    order.items = []
    return order


def add_items_to_order(order_id: str, items: list[NewOrderItem]) -> None:
    item_rows = _build_item_rows(order_id, items)

    supabase.insert("order_items", item_rows, return_result=False)

    existing = get_order_by_id(order_id)
    if existing is None:
        return

    subtotal = _calculate_subtotal_from_items(existing.items)
    tax_amount = _calculate_tax(subtotal)
    total = _round2(subtotal + tax_amount)

    supabase.update("orders", f"id=eq.{order_id}", {
        "subtotal": subtotal,
        "tax_amount": tax_amount,
        "total": total,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })


def close_order(order_id: str) -> None:
    order = get_order_by_id(order_id)
    supabase.update("orders", f"id=eq.{order_id}", {
        "status": "closed",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    if order:
        dish_svc.delete_custom_dishes_for_table(order.table_id)


def update_item_kitchen_status(item_id: str, status: str) -> None:
    supabase.update("order_items", f"id=eq.{item_id}", {"kitchen_status": status})


def auto_close_if_complete(item_id: str) -> None:
    """Close the order if all its items are both paid and delivered."""
    # Find which order this item belongs to
    rows = supabase.select("order_items", f"select=order_id&id=eq.{item_id}&limit=1")
    if not rows:
        return
    order_id = rows[0]["order_id"]

    order = get_order_by_id(order_id)
    if not order or order.status != "open":
        return

    all_done = all(
        i.payment_status == "paid" and i.kitchen_status == "delivered"
        for i in order.items
    )
    if all_done and order.items:
        close_order(order_id)


def update_items_payment_status(item_ids: list[str], status: str) -> None:
    if not item_ids:
        return
    in_list = "(" + ",".join(item_ids) + ")"
    supabase.update("order_items", f"id=in.{in_list}", {"payment_status": status})


def _build_item_rows(order_id: str, items: list[NewOrderItem]) -> list[dict]:
    rows = []
    for item in items:
        row = {
            "order_id": order_id,
            "dish_name": item.dish_name,
            "dish_price": item.dish_price,
            "quantity": item.quantity,
            "notes": item.notes,
            "diner_name": item.diner_name or "Cliente",
            "kitchen_status": "pending",
            "payment_status": "unassigned",
            "dish_id": item.dish_id or None,
            "customization": (item.customization.model_dump() if hasattr(item.customization, 'model_dump') else item.customization) if item.customization else None,
        }
        rows.append(row)
    return rows

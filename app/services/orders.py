from __future__ import annotations
import math
from datetime import datetime, timezone

from app.db import supabase
from app.models import NewOrderItem, Order, OrderItem

TAX_RATE_ES = 10.0  # Spain restaurant tax rate (%)


def _round2(v: float) -> float:
    return math.floor(v * 100 + 0.5) / 100


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

    item_rows = []
    for item in items:
        diner_name = item.diner_name if item.diner_name else "Cliente"
        item_rows.append({
            "order_id": order.id,
            "dish_name": item.dish_name,
            "dish_price": item.dish_price,
            "quantity": item.quantity,
            "notes": item.notes,
            "diner_name": diner_name,
            "kitchen_status": "pending",
            "payment_status": "unassigned",
        })

    supabase.insert("order_items", item_rows, return_result=False)

    order.items = []
    return order


def add_items_to_order(order_id: str, items: list[NewOrderItem]) -> None:
    item_rows = []
    for item in items:
        diner_name = item.diner_name if item.diner_name else "Cliente"
        item_rows.append({
            "order_id": order_id,
            "dish_name": item.dish_name,
            "dish_price": item.dish_price,
            "quantity": item.quantity,
            "notes": item.notes,
            "diner_name": diner_name,
            "kitchen_status": "pending",
            "payment_status": "unassigned",
        })

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
    supabase.update("orders", f"id=eq.{order_id}", {
        "status": "closed",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })


def update_item_kitchen_status(item_id: str, status: str) -> None:
    supabase.update("order_items", f"id=eq.{item_id}", {"kitchen_status": status})


def update_items_payment_status(item_ids: list[str], status: str) -> None:
    if not item_ids:
        return
    in_list = "(" + ",".join(item_ids) + ")"
    supabase.update("order_items", f"id=in.{in_list}", {"payment_status": status})

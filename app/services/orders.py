from __future__ import annotations
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timezone
from typing import Optional
from app.db.supabase import get_client
from app.models import NewOrderItem, Order, OrderItem
from app.services import dishes as dish_svc
from app.services import stock as stock_svc

TAX_RATE_ES = 10.0  # Spain restaurant tax rate (%)


def _round2(v: float) -> float:
    return float(Decimal(str(v)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _calculate_subtotal(items: list[NewOrderItem], resolved_prices: dict[int, float] | None = None) -> float:
    """Calculate subtotal. If resolved_prices is given, use server-side prices."""
    if resolved_prices:
        return sum(resolved_prices.get(idx, i.dish_price) * i.quantity for idx, i in enumerate(items))
    return sum(i.dish_price * i.quantity for i in items)


def _calculate_subtotal_from_items(items: list[OrderItem]) -> float:
    return sum(i.dish_price * i.quantity for i in items)


def _calculate_tax(subtotal: float) -> float:
    return _round2(subtotal * TAX_RATE_ES / 100)


def _get_tenant_tables(tenant_id: str) -> list[dict]:
    return get_client().table("restaurant_tables").select("id, number, label").eq("tenant_id", tenant_id).eq("is_active", True).execute().data or []


def _get_tenant_table_ids(tenant_id: str) -> list[str]:
    return [r["id"] for r in _get_tenant_tables(tenant_id)]


def _attach_table_label(row: dict) -> dict:
    table_id = row.get("table_id")
    if not table_id:
        return row
    tables = get_client().table("restaurant_tables").select("label, number").eq("id", table_id).limit(1).execute().data or []
    if tables:
        label = tables[0].get("label")
        if label:
            row["table_label"] = label
    return row


def fetch_orders(tenant_id: str, status: str, kitchen_only: bool = False) -> list[Order]:
    tables = _get_tenant_tables(tenant_id)
    table_ids = [r["id"] for r in tables]
    if not table_ids:
        return []
    table_labels = {r["id"]: r.get("label") for r in tables if r.get("label")}

    q = get_client().table("orders").select("*, items:order_items(*)").eq("status", status).in_("table_id", table_ids)
    if status == "closed":
        q = q.order("updated_at", desc=True).limit(100)
    else:
        q = q.order("created_at", desc=False).limit(1000)

    rows = q.execute().data or []
    for row in rows:
        label = table_labels.get(row.get("table_id"))
        if label:
            row["table_label"] = label
    orders = [Order(**row) for row in rows]

    if kitchen_only:
        for order in orders:
            order.items = [item for item in order.items if item.kitchen_status is not None]
        # Drop orders with no kitchen items
        orders = [o for o in orders if o.items]

    return orders


def get_order_by_id(order_id: str) -> Order | None:
    rows = get_client().table("orders").select("*, items:order_items(*)").eq("id", order_id).limit(1).execute().data or []
    if not rows:
        return None
    return Order(**_attach_table_label(rows[0]))


def get_open_order_for_table(table_id: str) -> Order | None:
    rows = get_client().table("orders").select("*, items:order_items(*)").eq("table_id", table_id).eq("status", "open").order("created_at", desc=True).limit(1).execute().data or []
    if not rows:
        return None
    return Order(**_attach_table_label(rows[0]))


def create_order(table_id: str, table_number: int, items: list[NewOrderItem], tenant_id: str = "") -> Order:
    # Resolve prices server-side before calculating totals
    precomputed = _resolve_ingredient_customizations(items)
    resolved_prices = precomputed[0]
    subtotal = _calculate_subtotal(items, resolved_prices)
    tax_amount = _calculate_tax(subtotal)
    total = _round2(subtotal + tax_amount)

    order_row = {
        "table_id": table_id,
        "table_number": table_number,
        "status": "open",
        "subtotal": subtotal,
        "tax_amount": tax_amount,
        "total": total,
        "tenant_id": tenant_id,
    }

    inserted = get_client().table("orders").insert(order_row).execute().data
    if not inserted:
        raise RuntimeError("failed to create order")
    order = Order(**_attach_table_label(inserted[0]))

    _build_and_insert_items(order.id, items, precomputed=precomputed)

    # Deduct ingredients from stock
    stock_svc.deduct_stock_for_items(items, tenant_id)

    get_client().table("restaurant_tables").update({"status": "in_kitchen", "active_order_id": order.id}).eq("id", table_id).execute()

    order.items = []
    return order


def add_items_to_order(order_id: str, items: list[NewOrderItem]) -> None:
    _build_and_insert_items(order_id, items)

    existing = get_order_by_id(order_id)
    if existing is None:
        return

    # Deduct ingredients from stock
    if existing.tenant_id:
        stock_svc.deduct_stock_for_items(items, existing.tenant_id)
    if existing.table_id:
        get_client().table("restaurant_tables").update({"status": "in_kitchen"}).eq("id", existing.table_id).execute()

    subtotal = _calculate_subtotal_from_items(existing.items)
    tax_amount = _calculate_tax(subtotal)
    total = _round2(subtotal + tax_amount)

    get_client().table("orders").update({
        "subtotal": subtotal,
        "tax_amount": tax_amount,
        "total": total,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", order_id).execute()


def close_order(order_id: str, tenant_id: str | None = None) -> None:
    order = get_order_by_id(order_id)
    if order is None:
        return
    if tenant_id and order.tenant_id != tenant_id:
        raise ValueError("order does not belong to this tenant")
    # Guard: skip if not open — prevents double-close from wiping the next
    # session's custom_dishes. custom_dishes are scoped to the active table
    # session (table_id), not to a specific order, so the delete below is
    # only safe when this order is still the active one.
    if order.status != "open":
        return
    get_client().table("orders").update({
        "status": "closed",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", order_id).execute()
    get_client().table("restaurant_tables").update({"status": "available", "active_order_id": None}).eq("id", order.table_id).execute()
    dish_svc.delete_custom_dishes_for_table(order.table_id)


def update_item_kitchen_status(item_id: str, status: str, tenant_id: str) -> None:
    order_id = _assert_item_owner(item_id, tenant_id)
    get_client().table("order_items").update({"kitchen_status": status}).eq("id", item_id).execute()
    _sync_table_status_from_order(order_id)


def _sync_table_status_from_order(order_id: str) -> None:
    order = get_order_by_id(order_id)
    if not order or order.status != "open":
        return

    kitchen_items = [
        item for item in order.items
        if item.kitchen_status is not None and item.kitchen_status != "cancelled"
    ]
    if not kitchen_items:
        return

    if any(item.kitchen_status in {"pending", "cooking", "ready"} for item in kitchen_items):
        next_status = "in_kitchen"
    elif all(item.kitchen_status == "delivered" for item in kitchen_items):
        next_status = "served"
    else:
        return

    get_client().table("restaurant_tables").update({"status": next_status}).eq("id", order.table_id).execute()


def _maybe_close_order(order_id: str) -> None:
    """Close order if all items are paid and delivered (or have no kitchen status)."""
    order = get_order_by_id(order_id)
    if not order or order.status != "open":  # close_order also guards this, but explicit here for clarity
        return
    all_done = all(
        i.payment_status == "paid" and (i.kitchen_status is None or i.kitchen_status == "delivered")
        for i in order.items
    )
    if all_done and order.items:
        close_order(order_id)


def auto_close_if_complete(item_id: str) -> None:
    """Close the order containing item_id if all its items are paid and delivered."""
    rows = get_client().table("order_items").select("order_id").eq("id", item_id).limit(1).execute().data or []
    if not rows:
        return
    _maybe_close_order(rows[0]["order_id"])


def auto_close_orders_for_items(item_ids: list[str]) -> None:
    """Batch version: one SELECT to resolve order_ids, then check each unique order once."""
    if not item_ids:
        return
    rows = get_client().table("order_items").select("order_id").in_("id", item_ids).execute().data or []
    for order_id in {r["order_id"] for r in rows}:
        _maybe_close_order(order_id)


def _recalculate_order_totals(order_id: str) -> None:
    """Recalculate and update subtotal, tax_amount, and total for an order."""
    order = get_order_by_id(order_id)
    if order is None:
        return

    subtotal = _calculate_subtotal_from_items(order.items)
    tax_amount = _calculate_tax(subtotal)
    total = _round2(subtotal + tax_amount)

    get_client().table("orders").update({
        "subtotal": subtotal,
        "tax_amount": tax_amount,
        "total": total,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", order_id).execute()


def _assert_item_owner(item_id: str, tenant_id: str) -> str:
    """Verify item belongs to tenant. Returns order_id."""
    rows = get_client().table("order_items").select("order_id, order:orders(tenant_id)").eq("id", item_id).limit(1).execute().data or []
    if not rows or rows[0].get("order", {}).get("tenant_id") != tenant_id:
        raise ValueError(f"order item {item_id} not found")
    return rows[0]["order_id"]


def delete_order_item(item_id: str, tenant_id: str) -> None:
    """Delete a single order item and recalculate parent order totals."""
    order_id = _assert_item_owner(item_id, tenant_id)

    # Get item details before deleting to restore stock
    item_rows = get_client().table("order_items").select("dish_id, quantity").eq("id", item_id).limit(1).execute().data or []
    if item_rows:
        item = item_rows[0]
        if item.get("dish_id"):
            # Create a temporary NewOrderItem to use with stock restoration
            temp_item = NewOrderItem(
                dish_name="",
                dish_price=0,
                quantity=item.get("quantity", 0),
                dish_id=item.get("dish_id")
            )
            # Restore stock by reversing the deduction
            stock_svc.restore_stock_for_items([temp_item], tenant_id)

    get_client().table("order_items").delete().eq("id", item_id).execute()
    _recalculate_order_totals(order_id)


def update_order_item_quantity(item_id: str, quantity: int, tenant_id: str) -> None:
    """Update the quantity of a single order item and recalculate parent order totals."""
    order_id = _assert_item_owner(item_id, tenant_id)

    # Get old quantity to handle stock adjustment
    item_rows = get_client().table("order_items").select("dish_id, quantity").eq("id", item_id).limit(1).execute().data or []
    if item_rows:
        item = item_rows[0]
        old_qty = float(item.get("quantity", 0))
        new_qty = float(quantity)
        qty_diff = new_qty - old_qty

        if item.get("dish_id") and qty_diff != 0:
            # If quantity decreased, restore stock; if increased, deduct more
            temp_item = NewOrderItem(
                dish_name="",
                dish_price=0,
                quantity=abs(qty_diff),
                dish_id=item.get("dish_id")
            )
            if qty_diff > 0:
                # Quantity increased - deduct more stock
                stock_svc.deduct_stock_for_items([temp_item], tenant_id)
            else:
                # Quantity decreased - restore stock
                stock_svc.restore_stock_for_items([temp_item], tenant_id)

    get_client().table("order_items").update({"quantity": quantity}).eq("id", item_id).execute()
    _recalculate_order_totals(order_id)


def update_order_item_price(item_id: str, price: float, tenant_id: str, reason: Optional[str] = None) -> None:
    """Update the price of a single order item and recalculate parent order totals."""
    order_id = _assert_item_owner(item_id, tenant_id)
    update_data: dict = {"dish_price": price}

    # Fetch current item to preserve original price on first override
    rows = get_client().table("order_items").select("dish_price, original_price").eq("id", item_id).limit(1).execute().data or []
    if not rows:
        raise ValueError(f"order item {item_id} not found")

    if rows[0].get("original_price") is None:
        update_data["original_price"] = rows[0]["dish_price"]
    if reason:
        update_data["price_override_reason"] = reason

    get_client().table("order_items").update(update_data).eq("id", item_id).execute()
    _recalculate_order_totals(order_id)


def update_items_payment_status(item_ids: list[str], status: str, tenant_id: str) -> None:
    if not item_ids:
        return
    rows = get_client().table("order_items").select("id, order:orders(tenant_id)").in_("id", item_ids).execute().data or []
    if len(rows) != len(item_ids):
        raise ValueError("one or more order items not found")
    for row in rows:
        if row.get("order", {}).get("tenant_id") != tenant_id:
            raise ValueError(f"order item {row['id']} does not belong to this tenant")
    get_client().table("order_items").update({"payment_status": status}).in_("id", item_ids).execute()


def update_items_payment_portions(allocations: list[dict], tenant_id: str) -> list[str]:
    """Mark paid portions for split-bill items without closing the whole item too early."""
    if not allocations:
        return []

    item_ids = [a["item_id"] for a in allocations]
    rows = (
        get_client()
        .table("order_items")
        .select("id,payment_status,split_portions,paid_portions,order:orders(tenant_id)")
        .in_("id", item_ids)
        .execute()
        .data
        or []
    )
    if len(rows) != len(set(item_ids)):
        raise ValueError("one or more order items not found")

    row_by_id = {row["id"]: row for row in rows}
    updated_ids: list[str] = []
    for allocation in allocations:
        item_id = allocation["item_id"]
        row = row_by_id[item_id]
        if row.get("order", {}).get("tenant_id") != tenant_id:
            raise ValueError(f"order item {item_id} does not belong to this tenant")

        current_split = max(1, int(row.get("split_portions") or 1))
        current_paid = current_split if row.get("payment_status") == "paid" else int(row.get("paid_portions") or 0)
        requested_split = max(current_split, int(allocation.get("split_portions") or 1))
        portions = max(1, int(allocation.get("portions") or 1))
        remaining = max(0, requested_split - current_paid)
        if remaining == 0:
            continue

        new_paid = min(requested_split, current_paid + min(portions, remaining))
        new_status = "paid" if new_paid >= requested_split else "unassigned"
        get_client().table("order_items").update({
            "split_portions": requested_split,
            "paid_portions": new_paid,
            "payment_status": new_status,
        }).eq("id", item_id).execute()
        updated_ids.append(item_id)

    return updated_ids


def _enrich_customization(cust: dict) -> dict:
    """Resolve ingredient UUIDs to names in customization for display."""
    if not cust:
        return cust

    # Collect all ingredient IDs that need name resolution
    ids_to_resolve: set[str] = set()

    for added in cust.get("added_ingredients") or []:
        if isinstance(added, dict) and "ingredient_id" in added and "name" not in added:
            ids_to_resolve.add(added["ingredient_id"])

    for removed in cust.get("removed_ingredients") or []:
        if isinstance(removed, str) and len(removed) > 20:  # Looks like UUID
            ids_to_resolve.add(removed)

    if not ids_to_resolve:
        return cust

    # Batch-fetch names
    rows = get_client().table("ingredients").select("id, name").in_("id", list(ids_to_resolve)).execute().data or []
    name_map = {r["id"]: r["name"] for r in rows}

    # Enrich added_ingredients
    if cust.get("added_ingredients"):
        for added in cust["added_ingredients"]:
            if isinstance(added, dict) and "name" not in added:
                added["name"] = name_map.get(added.get("ingredient_id", ""), "")

    # Enrich removed_ingredients: replace UUIDs with names
    if cust.get("removed_ingredients"):
        cust["removed_ingredients"] = [
            name_map.get(rid, rid) if isinstance(rid, str) and len(rid) > 20 else rid
            for rid in cust["removed_ingredients"]
        ]

    return cust


def _lookup_requires_kitchen(category_ids: set[str]) -> dict[str, bool]:
    """Batch-fetch requires_kitchen for a set of category IDs."""
    if not category_ids:
        return {}
    rows = get_client().table("categories").select("id, requires_kitchen").in_("id", list(category_ids)).execute().data or []
    return {row["id"]: row["requires_kitchen"] for row in rows}


def _resolve_ingredient_customizations(
    items: list[NewOrderItem],
) -> tuple[dict[int, float], dict[int, list[dict]]]:
    """Validate customizations and resolve server-side prices.

    Returns:
        resolved_prices: {item_index: unit_price} for items with dish_id
        ingredient_rows: {item_index: [row_dicts for order_item_ingredients]}
    """
    resolved_prices: dict[int, float] = {}
    ingredient_rows: dict[int, list[dict]] = {}

    # Collect all dish_ids that need price lookup
    dish_ids = {item.dish_id for item in items if item.dish_id}
    if not dish_ids:
        return resolved_prices, ingredient_rows

    # Batch-fetch dish base prices and variable-price flag
    dish_prices: dict[str, float] = {}
    dish_max_extras: dict[str, int | None] = {}
    dish_variable_price: dict[str, bool] = {}
    for did in dish_ids:
        rows = get_client().table("dishes").select("id, price, max_extra_choices, is_variable_price").eq("id", did).limit(1).execute().data or []
        if rows:
            dish_prices[did] = float(rows[0]["price"])
            dish_max_extras[did] = rows[0].get("max_extra_choices")
            dish_variable_price[did] = rows[0].get("is_variable_price", False)

    # Process each item
    for idx, item in enumerate(items):
        if not item.dish_id or item.dish_id not in dish_prices:
            continue

        # Explicit price override (e.g. habitual customer discount)
        if item.original_price is not None:
            resolved_prices[idx] = item.dish_price
            continue

        base_price = dish_prices[item.dish_id]
        cust = item.customization
        if not cust or (not cust.get("added_ingredients") and not cust.get("removed_ingredients")):
            # No customization — use server-side base price, unless dish
            # is variable-price (trust frontend price)
            if dish_variable_price.get(item.dish_id, False):
                resolved_prices[idx] = item.dish_price
            else:
                resolved_prices[idx] = base_price
            continue

        added = cust.get("added_ingredients") or []
        removed = cust.get("removed_ingredients") or []

        # Validate max_extra_choices
        max_extras = dish_max_extras.get(item.dish_id)
        if max_extras is not None and len(added) > max_extras:
            raise ValueError(
                f"dish {item.dish_id}: max {max_extras} extra ingredients allowed, got {len(added)}"
            )

        # Fetch dish_ingredients for validation
        di_rows = get_client().table("dish_ingredients").select("ingredient_id, present").eq("dish_id", item.dish_id).execute().data or []
        dish_ingredient_map: dict[str, bool] = {
            r["ingredient_id"]: r["present"] for r in di_rows
        }

        # Validate and resolve added ingredients
        extra_total = 0.0
        item_ing_rows: list[dict] = []

        if added:
            added_ids = [a["ingredient_id"] for a in added]
            ing_rows = get_client().table("ingredients").select("id, extra_price").in_("id", added_ids).execute().data or []
            ing_price_map = {r["id"]: float(r["extra_price"]) for r in ing_rows}

            for a in added:
                ing_id = a["ingredient_id"]
                # Must exist in ingredients table
                if ing_id not in ing_price_map:
                    raise ValueError(f"ingredient {ing_id} not found")
                # Must belong to this dish
                if ing_id not in dish_ingredient_map:
                    raise ValueError(
                        f"ingredient {ing_id} does not belong to dish {item.dish_id}"
                    )
                # Must be non-default (present=false)
                if dish_ingredient_map.get(ing_id, True):
                    raise ValueError(
                        f"ingredient {ing_id} is a default ingredient, cannot be added as extra"
                    )

                real_price = ing_price_map[ing_id]
                extra_total += real_price
                item_ing_rows.append({
                    "ingredient_id": ing_id,
                    "action": "added",
                })

        # Validate removed ingredients
        for rid in removed:
            if rid not in dish_ingredient_map:
                raise ValueError(
                    f"ingredient {rid} does not belong to dish {item.dish_id}"
                )
            if not dish_ingredient_map.get(rid, True):
                raise ValueError(
                    f"ingredient {rid} is not a default ingredient, cannot be removed"
                )
            item_ing_rows.append({
                "ingredient_id": rid,
                "action": "removed",
            })

        resolved_prices[idx] = _round2(base_price + extra_total)
        if item_ing_rows:
            ingredient_rows[idx] = item_ing_rows

    return resolved_prices, ingredient_rows


def _build_and_insert_items(
    order_id: str,
    items: list[NewOrderItem],
    precomputed: tuple[dict[int, float], dict[int, list[dict]]] | None = None,
) -> None:
    """Build item rows, insert them, and write order_item_ingredients."""
    if precomputed:
        resolved_prices, ingredient_rows = precomputed
    else:
        resolved_prices, ingredient_rows = _resolve_ingredient_customizations(items)

    # Batch-fetch requires_kitchen for all items with a category_id
    unique_cat_ids = {item.category_id for item in items if item.category_id}
    kitchen_map = _lookup_requires_kitchen(unique_cat_ids)

    rows = []
    for idx, item in enumerate(items):
        # Determine kitchen_status based on category's requires_kitchen flag
        if item.category_id and item.category_id in kitchen_map:
            kitchen_status = "pending" if kitchen_map[item.category_id] else None
        else:
            kitchen_status = "pending"

        # Use resolved price if available, otherwise keep frontend price
        dish_price = resolved_prices.get(idx, item.dish_price)

        # Enrich customization with ingredient names for display
        enriched_cust = None
        if item.customization:
            raw_cust = item.customization.model_dump() if hasattr(item.customization, 'model_dump') else item.customization
            enriched_cust = _enrich_customization(raw_cust)

        row = {
            "order_id": order_id,
            "dish_name": item.dish_name,
            "dish_price": dish_price,
            "quantity": item.quantity,
            "notes": item.notes,
            "diner_name": item.diner_name or "Cliente",
            "kitchen_status": kitchen_status,
            "payment_status": "unassigned",
            "dish_id": item.dish_id or None,
            "category_id": item.category_id or None,
            "customization": enriched_cust,
            "original_price": item.original_price,
            "price_override_reason": item.price_override_reason,
        }
        rows.append(row)

    # Insert with return to get IDs (needed for ingredient rows)
    if ingredient_rows:
        inserted = get_client().table("order_items").insert(rows).execute().data
        if not inserted:
            raise RuntimeError("failed to insert order items")

        # Insert order_item_ingredients
        all_ing_rows: list[dict] = []
        for idx, ing_list in ingredient_rows.items():
            order_item_id = inserted[idx]["id"]
            for ing in ing_list:
                all_ing_rows.append({
                    "order_item_id": order_item_id,
                    "ingredient_id": ing["ingredient_id"],
                    "action": ing["action"],
                })

        if all_ing_rows:
            get_client().table("order_item_ingredients").insert(all_ing_rows).execute()
    else:
        get_client().table("order_items").insert(rows).execute()

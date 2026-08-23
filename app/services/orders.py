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
    rt = row.get("restaurant_tables")
    if rt:
        if isinstance(rt, list) and rt:
            rt = rt[0]
        if isinstance(rt, dict):
            label = rt.get("label")
            if label:
                row["table_label"] = label
                return row

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
    table_ids = _get_tenant_table_ids(tenant_id)

    if table_ids:
        q = get_client().table("orders").select("*, items:order_items(*)").eq("status", status).or_(f"tenant_id.eq.{tenant_id},table_id.in.({','.join(table_ids)})")
    else:
        q = get_client().table("orders").select("*, items:order_items(*)").eq("status", status).eq("tenant_id", tenant_id)

    if status == "closed":
        q = q.order("updated_at", desc=True).limit(100)
    else:
        q = q.order("created_at", desc=False).limit(1000)

    rows = q.execute().data or []
    orders = [Order(**_attach_table_label(row)) for row in rows]

    if kitchen_only:
        for order in orders:
            order.items = [item for item in order.items if item.kitchen_status is not None]
        # Drop orders with no kitchen items
        orders = [o for o in orders if o.items]

    return orders


def get_order_by_id(order_id: str) -> Order | None:
    rows = get_client().table("orders").select("*, items:order_items(*), restaurant_tables(label, number)").eq("id", order_id).limit(1).execute().data or []
    if not rows:
        return None
    return Order(**_attach_table_label(rows[0]))


def get_open_order_for_table(table_id: str) -> Order | None:
    rows = get_client().table("orders").select("*, items:order_items(*), restaurant_tables(label, number)").eq("table_id", table_id).eq("status", "open").order("created_at", desc=True).limit(1).execute().data or []
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


def update_item_split_portions(item_id: str, split_portions: int, tenant_id: str) -> None:
    """Update split portions for a single order item (diner-initiated)."""
    order_id = _assert_item_owner(item_id, tenant_id)
    rows = (
        get_client()
        .table("order_items")
        .select("paid_portions, payment_status")
        .eq("id", item_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows:
        raise ValueError("item not found")

    if rows[0].get("payment_status") == "paid":
        raise ValueError("cannot split paid item")

    paid = int(rows[0].get("paid_portions") or 0)
    if split_portions < paid:
        raise ValueError(f"split_portions cannot be less than paid_portions ({paid})")

    get_client().table("order_items").update({
        "split_portions": split_portions,
    }).eq("id", item_id).execute()



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
    
    if len(dish_ids) == 1:
        did = list(dish_ids)[0]
        rows = get_client().table("dishes").select("id, price, max_extra_choices, is_variable_price").eq("id", did).limit(1).execute().data or []
    else:
        rows = (
            get_client()
            .table("dishes")
            .select("id, price, max_extra_choices, is_variable_price")
            .in_("id", list(dish_ids))
            .execute()
            .data
            or []
        )
    for r in rows:
        did = r["id"]
        dish_prices[did] = float(r["price"])
        dish_max_extras[did] = r.get("max_extra_choices")
        dish_variable_price[did] = r.get("is_variable_price", False)

    # Batch-fetch dish_ingredients for all dishes that have customization
    customized_dish_ids = {
        item.dish_id for item in items 
        if item.dish_id and item.customization and 
        (item.customization.get("added_ingredients") or item.customization.get("removed_ingredients"))
    }
    
    di_by_dish: dict[str, list[dict]] = {}
    if customized_dish_ids:
        if len(customized_dish_ids) == 1:
            did = list(customized_dish_ids)[0]
            di_rows = get_client().table("dish_ingredients").select("ingredient_id, present, can_remove, discount_price").eq("dish_id", did).execute().data or []
            for r in di_rows:
                r["dish_id"] = did
        else:
            di_rows = (
                get_client()
                .table("dish_ingredients")
                .select("dish_id, ingredient_id, present, can_remove, discount_price")
                .in_("dish_id", list(customized_dish_ids))
                .execute()
                .data
                or []
            )
        for r in di_rows:
            did = r.get("dish_id")
            if did:
                if did not in di_by_dish:
                    di_by_dish[did] = []
                di_by_dish[did].append(r)

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
            # is variable-price or it's a menu item (trust frontend price)
            if dish_variable_price.get(item.dish_id, False) or (cust and cust.get("menu_group")):
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

        # Get pre-fetched dish_ingredients for this dish
        di_rows = di_by_dish.get(item.dish_id) or []
        dish_ingredient_map: dict[str, dict] = {
            r["ingredient_id"]: r for r in di_rows
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
                di_info = dish_ingredient_map[ing_id]
                # Must be non-default (present=false)
                if di_info.get("present", True):
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
            di_info = dish_ingredient_map[rid]
            if not di_info.get("present", True):
                raise ValueError(
                    f"ingredient {rid} is not a default ingredient, cannot be removed"
                )
            if not di_info.get("can_remove", False):
                raise ValueError(
                    f"ingredient {rid} cannot be removed (removal disabled)"
                )
            extra_total -= float(di_info.get("discount_price", 0.0))
            item_ing_rows.append({
                "ingredient_id": rid,
                "action": "removed",
            })

        if cust and cust.get("menu_group"):
            resolved_prices[idx] = item.dish_price
        else:
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
        # Both kitchen and bar items start as "pending"
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
            "source": item.source or "management",
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


def _build_and_insert_prepay_items(
    order_id: str,
    items: list[NewOrderItem],
    precomputed: tuple[dict[int, float], dict[int, list[dict]]] | None = None,
    diner_name: str = "Comensal",
    notes: Optional[str] = None,
) -> None:
    """Build item rows for prepay with payment_status='paid' and kitchen_status='pending'."""
    if precomputed:
        resolved_prices, ingredient_rows = precomputed
    else:
        resolved_prices, ingredient_rows = _resolve_ingredient_customizations(items)

    dish_ids_to_lookup = [i.dish_id for i in items if i.dish_id and not i.category_id]
    dish_cat_map: dict[str, Optional[str]] = {}
    if dish_ids_to_lookup:
        dish_rows = get_client().table("dishes").select("id, category_id").in_("id", dish_ids_to_lookup).execute().data or []
        dish_cat_map = {d["id"]: d.get("category_id") for d in dish_rows}

    rows = []
    for idx, item in enumerate(items):
        kitchen_status = "pending"
        dish_price = resolved_prices.get(idx, item.dish_price)

        enriched_cust = None
        if item.customization:
            raw_cust = item.customization.model_dump() if hasattr(item.customization, 'model_dump') else item.customization
            enriched_cust = _enrich_customization(raw_cust)

        item_notes = item.notes or notes or None
        cat_id = item.category_id or (dish_cat_map.get(item.dish_id) if item.dish_id else None)

        row = {
            "order_id": order_id,
            "dish_name": item.dish_name,
            "dish_price": dish_price,
            "quantity": item.quantity,
            "notes": item_notes,
            "diner_name": item.diner_name or diner_name or "Comensal",
            "kitchen_status": kitchen_status,
            "payment_status": "paid",
            "split_portions": 1,
            "paid_portions": 1,
            "dish_id": item.dish_id or None,
            "category_id": cat_id,
            "customization": enriched_cust,
            "original_price": item.original_price,
            "price_override_reason": item.price_override_reason,
            "source": item.source or "customer",
        }
        rows.append(row)

    if ingredient_rows:
        inserted = get_client().table("order_items").insert(rows).execute().data
        if not inserted:
            raise RuntimeError("failed to insert prepay order items")

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


def create_prepay_order(
    table_id: str,
    table_number: int,
    items: list[NewOrderItem],
    payment_method: str,
    tenant_id: str = "",
    diner_name: str = "Comensal",
    customer_email: Optional[str] = None,
    customer_phone: Optional[str] = None,
    notes: Optional[str] = None,
    tracking_code: Optional[str] = None,
) -> tuple[Order, str, str, Optional[str]]:
    """Creates or updates an order with immediate pre-payment and dispatches items to kitchen.

    Returns: (order, tracking_code, tracking_url, payment_id)
    """
    precomputed = _resolve_ingredient_customizations(items)
    resolved_prices = precomputed[0]
    subtotal = _calculate_subtotal(items, resolved_prices)
    tax_amount = _calculate_tax(subtotal)
    total = _round2(subtotal + tax_amount)

    existing = None
    if tracking_code:
        raw_code = tracking_code.strip().upper()
        hex_prefix = raw_code[4:].lower() if raw_code.startswith("GOB-") else raw_code.lower()
        clean_prefix = "".join(c for c in hex_prefix if c in "0123456789abcdef")
        if len(clean_prefix) >= 6:
            start_uuid = (clean_prefix.ljust(8, "0") + "-0000-0000-0000-000000000000")[:36]
            end_uuid = (clean_prefix.ljust(8, "f") + "-ffff-ffff-ffff-ffffffffffff")[:36]
            rows = get_client().table("orders").select("id").eq("table_id", table_id).gte("id", start_uuid).lte("id", end_uuid).order("created_at", desc=True).limit(1).execute().data or []
            if rows:
                existing = get_order_by_id(rows[0]["id"])

    if existing:
        order_id = existing.id
        _build_and_insert_prepay_items(
            order_id, items, precomputed=precomputed, diner_name=diner_name, notes=notes
        )
        if tenant_id:
            stock_svc.deduct_stock_for_items(items, tenant_id)

        refreshed = get_order_by_id(order_id)
        if refreshed is None:
            raise RuntimeError("failed to refresh existing order")

        new_subtotal = _calculate_subtotal_from_items(refreshed.items)
        new_tax = _calculate_tax(new_subtotal)
        new_total = _round2(new_subtotal + new_tax)
        new_amount_paid = _round2(float(existing.subtotal + existing.tax_amount if existing.total is None else existing.total) + total)

        get_client().table("orders").update({
            "subtotal": new_subtotal,
            "tax_amount": new_tax,
            "total": new_total,
            "amount_paid": new_amount_paid,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", order_id).execute()

        get_client().table("restaurant_tables").update({
            "status": "in_kitchen",
            "active_order_id": order_id,
            "is_app_used": True,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", table_id).execute()
        order = get_order_by_id(order_id)
    else:
        order_row = {
            "table_id": table_id,
            "table_number": table_number,
            "status": "open",
            "subtotal": subtotal,
            "tax_amount": tax_amount,
            "total": total,
            "amount_paid": total,
            "tenant_id": tenant_id,
        }
        inserted = get_client().table("orders").insert(order_row).execute().data
        if not inserted:
            raise RuntimeError("failed to create prepay order")
        order = Order(**_attach_table_label(inserted[0]))
        order_id = order.id

        _build_and_insert_prepay_items(
            order_id, items, precomputed=precomputed, diner_name=diner_name, notes=notes
        )
        if tenant_id:
            stock_svc.deduct_stock_for_items(items, tenant_id)
        get_client().table("restaurant_tables").update({
            "status": "in_kitchen",
            "active_order_id": order_id,
            "is_app_used": True,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", table_id).execute()
        order = get_order_by_id(order_id)

    if order is None:
        raise RuntimeError("failed to retrieve finalized prepay order")

    tracking_code = f"GOB-{order.id[:6].upper()}"
    tracking_url = f"/track/{tracking_code}"

    # Insert payment record
    payment_row = {
        "order_id": order.id,
        "amount": total,
        "tip_amount": 0.0,
        "total_charged": total,
        "payment_method": payment_method or "card",
        "status": "confirmed",
        "reference": f"PREPAY-{tracking_code}",
    }
    payment_res = get_client().table("payments").insert(payment_row).execute().data
    payment_id = payment_res[0]["id"] if payment_res else None

    return order, tracking_code, tracking_url, payment_id


def get_order_tracking(tracking_code: str) -> dict | None:
    """Lookup order details by tracking code (e.g. GOB-A1B2C3 or order UUID)."""
    raw_code = tracking_code.strip().upper()
    if raw_code.startswith("GOB-"):
        hex_prefix = raw_code[4:].lower()
    else:
        hex_prefix = raw_code.lower()

    client = get_client()
    if len(hex_prefix) == 36 and "-" in hex_prefix:
        rows = client.table("orders").select("*, items:order_items(*), restaurant_tables(label, number)").eq("id", hex_prefix).execute().data or []
    else:
        # PostgreSQL UUID cannot be filtered with ILIKE in PostgREST, use hexadecimal range
        clean_prefix = "".join(c for c in hex_prefix if c in "0123456789abcdef")
        start_uuid = (clean_prefix.ljust(8, "0") + "-0000-0000-0000-000000000000")[:36]
        end_uuid = (clean_prefix.ljust(8, "f") + "-ffff-ffff-ffff-ffffffffffff")[:36]
        rows = client.table("orders").select("*, items:order_items(*), restaurant_tables(label, number)").gte("id", start_uuid).lte("id", end_uuid).order("created_at", desc=True).limit(1).execute().data or []

    if not rows:
        return None

    order_row = _attach_table_label(rows[0])
    order = Order(**order_row)

    tenant_name = ""
    tenant_slug = ""
    if order.tenant_id:
        t_rows = client.table("tenants").select("name, slug").eq("id", order.tenant_id).limit(1).execute().data or []
        if t_rows:
            tenant_name = t_rows[0].get("name", "")
            tenant_slug = t_rows[0].get("slug", "")

    total_items = len(order.items)
    pending_items = sum(1 for i in order.items if i.kitchen_status == "pending")
    cooking_items = sum(1 for i in order.items if i.kitchen_status == "cooking")
    ready_items = sum(1 for i in order.items if i.kitchen_status == "ready")
    delivered_items = sum(1 for i in order.items if i.kitchen_status == "delivered")

    if order.status == "closed" or (total_items > 0 and delivered_items == total_items):
        overall_stage = "delivered"
    elif cooking_items > 0 or ready_items > 0:
        overall_stage = "cooking"
    elif pending_items > 0:
        overall_stage = "in_kitchen"
    else:
        overall_stage = "received"

    p_rows = client.table("payments").select("id").eq("order_id", order.id).order("created_at", desc=True).limit(1).execute().data or []
    payment_id = p_rows[0]["id"] if p_rows else None

    return {
        "order_id": order.id,
        "tracking_code": f"GOB-{order.id[:6].upper()}",
        "table_id": order.table_id,
        "table_number": order.table_number,
        "table_label": order.table_label,
        "status": order.status,
        "subtotal": order.subtotal,
        "tax_amount": order.tax_amount,
        "total": order.total,
        "amount_paid": float(order_row.get("amount_paid") or order.total),
        "created_at": order.created_at,
        "updated_at": order.updated_at,
        "tenant_name": tenant_name,
        "tenant_slug": tenant_slug,
        "overall_stage": overall_stage,
        "total_items": total_items,
        "pending_items": pending_items,
        "cooking_items": cooking_items,
        "ready_items": ready_items,
        "delivered_items": delivered_items,
        "items": [i.model_dump() for i in order.items],
        "payment_id": payment_id,
    }


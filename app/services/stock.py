"""Stock/inventory deduction when orders are placed."""
from app.db.supabase import get_client
from app.models import NewOrderItem


def deduct_stock_for_items(items: list[NewOrderItem], tenant_id: str) -> None:
    """Deduct ingredients from inventory when order items are created.

    For each item in the order:
    1. Get the dish_id and quantity
    2. Skip ingredients that the client removed in the customization
    3. Find matching stock_items by ingredient name
    4. Deduct quantity from stock_items.current_quantity
    """
    if not items or not tenant_id:
        return

    for item in items:
        if not item.dish_id or item.quantity <= 0:
            continue

        # Extract removed ingredient IDs from customization
        removed_ids = []
        if item.customization and isinstance(item.customization, dict):
            raw_removed = item.customization.get("removed_ingredients") or []
            for r in raw_removed:
                if isinstance(r, dict) and "id" in r:
                    removed_ids.append(r["id"])
                elif isinstance(r, str):
                    removed_ids.append(r)

        ing_rows = get_client().table("dish_ingredients").select(
            "ingredient_id,ingredient:ingredients(id,name)"
        ).eq("dish_id", item.dish_id).execute().data or []

        if not ing_rows:
            continue

        for ing_row in ing_rows:
            ingredient = ing_row.get("ingredient")
            if not ingredient:
                continue

            ingredient_id = ingredient.get("id")
            if ingredient_id in removed_ids:
                # This ingredient was removed by the diner, skip stock deduction!
                continue

            ingredient_name = ingredient.get("name")
            if not ingredient_name:
                continue

            stock_rows = get_client().table("stock_items").select(
                "id,current_quantity,tenant_id"
            ).eq("name", ingredient_name).eq("tenant_id", tenant_id).limit(1).execute().data or []

            if not stock_rows:
                continue

            stock_item = stock_rows[0]
            current_qty = float(stock_item["current_quantity"])
            new_qty = max(0.0, current_qty - item.quantity)

            get_client().table("stock_items").update(
                {"current_quantity": new_qty}
            ).eq("id", stock_item["id"]).execute()

            get_client().table("stock_movements").insert({
                "stock_item_id": stock_item["id"],
                "type": "consumo",
                "quantity": -item.quantity,
                "quantity_before": current_qty,
                "quantity_after": new_qty,
                "notes": f"Consumo automático ({item.dish_name})",
                "tenant_id": tenant_id,
            }).execute()


def restore_stock_for_items(items: list[NewOrderItem], tenant_id: str) -> None:
    """Restore ingredients to inventory (reverse of deduction).

    Used when items are deleted or quantity is reduced.
    """
    if not items or not tenant_id:
        return

    for item in items:
        if not item.dish_id or item.quantity <= 0:
            continue

        # Extract removed ingredient IDs from customization
        removed_ids = []
        if item.customization and isinstance(item.customization, dict):
            raw_removed = item.customization.get("removed_ingredients") or []
            for r in raw_removed:
                if isinstance(r, dict) and "id" in r:
                    removed_ids.append(r["id"])
                elif isinstance(r, str):
                    removed_ids.append(r)

        ing_rows = get_client().table("dish_ingredients").select(
            "ingredient_id,ingredient:ingredients(id,name)"
        ).eq("dish_id", item.dish_id).execute().data or []

        if not ing_rows:
            continue

        for ing_row in ing_rows:
            ingredient = ing_row.get("ingredient")
            if not ingredient:
                continue

            ingredient_id = ingredient.get("id")
            if ingredient_id in removed_ids:
                # This ingredient was removed, so it was never deducted. Skip restoring!
                continue

            ingredient_name = ingredient.get("name")
            if not ingredient_name:
                continue

            stock_rows = get_client().table("stock_items").select(
                "id,current_quantity,tenant_id"
            ).eq("name", ingredient_name).eq("tenant_id", tenant_id).limit(1).execute().data or []

            if not stock_rows:
                continue

            stock_item = stock_rows[0]
            current_qty = float(stock_item["current_quantity"])
            new_qty = current_qty + item.quantity

            get_client().table("stock_items").update(
                {"current_quantity": new_qty}
            ).eq("id", stock_item["id"]).execute()

            get_client().table("stock_movements").insert({
                "stock_item_id": stock_item["id"],
                "type": "devolucion",
                "quantity": item.quantity,
                "quantity_before": current_qty,
                "quantity_after": new_qty,
                "notes": f"Devolución automática ({item.dish_name})",
                "tenant_id": tenant_id,
            }).execute()

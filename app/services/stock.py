"""Stock/inventory deduction when orders are placed."""
from app.db.supabase import get_client
from app.models import NewOrderItem


def deduct_stock_for_items(items: list[NewOrderItem], tenant_id: str) -> None:
    """Deduct ingredients from inventory when order items are created.

    For each item in the order:
    1. Get the dish_id and quantity
    2. Get all ingredients for that dish from dish_ingredients + ingredients
    3. Find matching stock_items by ingredient name
    4. Deduct quantity from stock_items.current_quantity
    """
    if not items or not tenant_id:
        return

    dish_qty_map: dict[str, float] = {}
    for item in items:
        if item.dish_id:
            dish_qty_map[item.dish_id] = dish_qty_map.get(item.dish_id, 0) + item.quantity

    if not dish_qty_map:
        return

    for dish_id, order_qty in dish_qty_map.items():
        ing_rows = get_client().table("dish_ingredients").select(
            "ingredient_id,ingredient:ingredients(id,name)"
        ).eq("dish_id", dish_id).execute().data or []

        if not ing_rows:
            continue

        for ing_row in ing_rows:
            ingredient = ing_row.get("ingredient")
            if not ingredient:
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
            new_qty = max(0.0, current_qty - order_qty)

            get_client().table("stock_items").update(
                {"current_quantity": new_qty}
            ).eq("id", stock_item["id"]).execute()

            get_client().table("stock_movements").insert({
                "stock_item_id": stock_item["id"],
                "type": "consumo",
                "quantity": -order_qty,
                "quantity_before": current_qty,
                "quantity_after": new_qty,
                "notes": "Consumo automático",
                "tenant_id": tenant_id,
            }).execute()


def restore_stock_for_items(items: list[NewOrderItem], tenant_id: str) -> None:
    """Restore ingredients to inventory (reverse of deduction).

    Used when items are deleted or quantity is reduced.
    """
    if not items or not tenant_id:
        return

    dish_qty_map: dict[str, float] = {}
    for item in items:
        if item.dish_id:
            dish_qty_map[item.dish_id] = dish_qty_map.get(item.dish_id, 0) + item.quantity

    if not dish_qty_map:
        return

    for dish_id, restore_qty in dish_qty_map.items():
        ing_rows = get_client().table("dish_ingredients").select(
            "ingredient_id,ingredient:ingredients(id,name)"
        ).eq("dish_id", dish_id).execute().data or []

        if not ing_rows:
            continue

        for ing_row in ing_rows:
            ingredient = ing_row.get("ingredient")
            if not ingredient:
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
            new_qty = current_qty + restore_qty

            get_client().table("stock_items").update(
                {"current_quantity": new_qty}
            ).eq("id", stock_item["id"]).execute()

            get_client().table("stock_movements").insert({
                "stock_item_id": stock_item["id"],
                "type": "devolucion",
                "quantity": restore_qty,
                "quantity_before": current_qty,
                "quantity_after": new_qty,
                "notes": "Devolución automática",
                "tenant_id": tenant_id,
            }).execute()

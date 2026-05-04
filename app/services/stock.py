"""Stock/inventory deduction when orders are placed."""
from app.db import supabase
from app.models import NewOrderItem


def deduct_stock_for_items(items: list[NewOrderItem], tenant_id: str) -> None:
    """Deduct ingredients from inventory when order items are created.

    For each item in the order:
    1. Get the dish_id and quantity
    2. Get all ingredients for that dish from dish_ingredients + ingredients
    3. Find matching stock_items by ingredient name
    4. Deduct quantity from stock_items.current_quantity
    """
    if not items:
        return

    # Collect all unique dish IDs with their quantities
    dish_qty_map: dict[str, float] = {}
    for item in items:
        if item.dish_id:
            dish_qty_map[item.dish_id] = dish_qty_map.get(item.dish_id, 0) + item.quantity

    if not dish_qty_map:
        return

    # For each dish, get its ingredients and deduct them
    for dish_id, order_qty in dish_qty_map.items():
        # Get all ingredients for this dish (joined with ingredients table to get names)
        ing_rows = supabase.select(
            "dish_ingredients",
            f"select=ingredient_id,ingredient:ingredients(id,name)"
            f"&dish_id=eq.{dish_id}",
        )

        if not ing_rows:
            continue

        # For each ingredient in the dish, deduct from stock
        for ing_row in ing_rows:
            ingredient = ing_row.get("ingredient")
            if not ingredient:
                continue

            ingredient_name = ingredient.get("name")
            if not ingredient_name:
                continue

            # Find the stock_item for this ingredient in this tenant by name
            # Use exact match first, fall back to case-insensitive
            stock_rows = supabase.select(
                "stock_items",
                f"select=id,current_quantity&name=eq.{ingredient_name}&tenant_id=eq.{tenant_id}&limit=1",
            )

            # If no exact match, try case-insensitive search
            if not stock_rows:
                stock_rows = supabase.select(
                    "stock_items",
                    f"select=id,current_quantity&name=ilike.*{ingredient_name}*&tenant_id=eq.{tenant_id}&limit=1",
                )

            if not stock_rows:
                continue

            stock_item = stock_rows[0]
            current_qty = float(stock_item["current_quantity"])
            new_qty = max(0.0, current_qty - order_qty)

            # Update stock
            supabase.update(
                "stock_items",
                f"id=eq.{stock_item['id']}",
                {"current_quantity": new_qty}
            )

            # Record movement as consumption
            movement_row = {
                "stock_item_id": stock_item["id"],
                "type": "consumo",
                "quantity": -order_qty,
                "quantity_before": current_qty,
                "quantity_after": new_qty,
                "notes": f"Consumo automático: orden",
                "tenant_id": tenant_id,
            }
            supabase.insert("stock_movements", movement_row, return_result=False)


def restore_stock_for_items(items: list[NewOrderItem], tenant_id: str) -> None:
    """Restore ingredients to inventory (reverse of deduction).

    Used when items are deleted or quantity is reduced.
    """
    if not items:
        return

    # Collect all unique dish IDs with their quantities
    dish_qty_map: dict[str, float] = {}
    for item in items:
        if item.dish_id:
            dish_qty_map[item.dish_id] = dish_qty_map.get(item.dish_id, 0) + item.quantity

    if not dish_qty_map:
        return

    # For each dish, get its ingredients and restore them
    for dish_id, restore_qty in dish_qty_map.items():
        # Get all ingredients for this dish (joined with ingredients table to get names)
        ing_rows = supabase.select(
            "dish_ingredients",
            f"select=ingredient_id,ingredient:ingredients(id,name)"
            f"&dish_id=eq.{dish_id}",
        )

        if not ing_rows:
            continue

        # For each ingredient in the dish, restore to stock
        for ing_row in ing_rows:
            ingredient = ing_row.get("ingredient")
            if not ingredient:
                continue

            ingredient_name = ingredient.get("name")
            if not ingredient_name:
                continue

            # Find the stock_item for this ingredient in this tenant by name
            stock_rows = supabase.select(
                "stock_items",
                f"select=id,current_quantity&name=eq.{ingredient_name}&tenant_id=eq.{tenant_id}&limit=1",
            )

            # If no exact match, try case-insensitive search
            if not stock_rows:
                stock_rows = supabase.select(
                    "stock_items",
                    f"select=id,current_quantity&name=ilike.*{ingredient_name}*&tenant_id=eq.{tenant_id}&limit=1",
                )

            if not stock_rows:
                continue

            stock_item = stock_rows[0]
            current_qty = float(stock_item["current_quantity"])
            new_qty = current_qty + restore_qty

            # Update stock
            supabase.update(
                "stock_items",
                f"id=eq.{stock_item['id']}",
                {"current_quantity": new_qty}
            )

            # Record movement as devolution/return
            movement_row = {
                "stock_item_id": stock_item["id"],
                "type": "devolucion",
                "quantity": restore_qty,
                "quantity_before": current_qty,
                "quantity_after": new_qty,
                "notes": f"Devolución automática: orden cancelada",
                "tenant_id": tenant_id,
            }
            supabase.insert("stock_movements", movement_row, return_result=False)

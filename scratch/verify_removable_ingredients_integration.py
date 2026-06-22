import os
import sys
from dotenv import load_dotenv

# Load env vars
load_dotenv("/Users/roger/Documents/app/gobbly/billsplit-api/.env")
sys.path.append("/Users/roger/Documents/app/gobbly/billsplit-api")

from app.db import supabase
from app.models import NewOrderItem
from app.services import stock as stock_svc
from app.services.orders import _resolve_ingredient_customizations

# Initialize database connection
supabase.init()
db = supabase.get_client()

def verify():
    # 1. Fetch a tenant
    tenants = db.table("tenants").select("id").limit(1).execute().data
    if not tenants:
        print("FAIL: No tenant found in DB")
        return
    tenant_id = tenants[0]["id"]
    print(f"Using Tenant ID: {tenant_id}")

    # 2. Fetch a dish that has ingredients
    junction_rows = db.table("dish_ingredients").select("dish_id").eq("present", True).limit(1).execute().data
    if not junction_rows:
        print("FAIL: No dish_ingredients found in DB. Make sure you seeded the Catalan dishes.")
        return
    dish_id = junction_rows[0]["dish_id"]
    
    # Fetch the dish details
    dish = db.table("dishes").select("*").eq("id", dish_id).execute().data[0]
    dish_name = dish["name"]
    dish_price = float(dish["price"])
    print(f"Using Dish: {dish_name} (ID: {dish_id}, Price: {dish_price}€)")

    # Fetch default ingredients of this dish
    di_rows = db.table("dish_ingredients").select("ingredient_id,present,can_remove,discount_price,ingredient:ingredients(id,name)").eq("dish_id", dish_id).eq("present", True).execute().data
    if not di_rows:
        print("FAIL: No default ingredients found for this dish.")
        return
    
    # We will pick the first default ingredient for our test
    test_di = di_rows[0]
    ingredient_id = test_di["ingredient_id"]
    ingredient_name = test_di["ingredient"]["name"]
    print(f"Targeting Ingredient: {ingredient_name} (ID: {ingredient_id})")

    # Keep original values to restore them at the end
    orig_can_remove = test_di.get("can_remove", False)
    orig_discount_price = float(test_di.get("discount_price", 0.0))
    print(f"Original config: can_remove={orig_can_remove}, discount_price={orig_discount_price}")

    # Ensure the ingredient has a matching stock item
    stock_rows = db.table("stock_items").select("id,current_quantity").eq("name", ingredient_name).eq("tenant_id", tenant_id).execute().data
    if not stock_rows:
        print(f"Creating temporary stock item for {ingredient_name}...")
        stock_item = db.table("stock_items").insert({
            "name": ingredient_name,
            "current_quantity": 10.0,
            "unit": "unitat",
            "cost_per_unit": 0.50,
            "tenant_id": tenant_id
        }).execute().data[0]
    else:
        stock_item = stock_rows[0]
    
    stock_item_id = stock_item["id"]
    stock_qty_before = float(stock_item["current_quantity"])
    print(f"Stock before test: {stock_qty_before} units")

    # Set up other default ingredients' stock so we can verify they get deducted
    other_default_names = []
    other_stock_befores = {}
    for di in di_rows[1:]:
        name = di["ingredient"]["name"]
        other_default_names.append(name)
        s_rows = db.table("stock_items").select("id,current_quantity").eq("name", name).eq("tenant_id", tenant_id).execute().data
        if not s_rows:
            # Create temporary stock item
            s_item = db.table("stock_items").insert({
                "name": name,
                "current_quantity": 5.0,
                "unit": "unitat",
                "cost_per_unit": 0.50,
                "tenant_id": tenant_id
            }).execute().data[0]
        else:
            s_item = s_rows[0]
        other_stock_befores[name] = float(s_item["current_quantity"])

    try:
        # TEST 1: Update configuration to can_remove=True and discount_price=1.50
        print("\n--- TEST 1: Pricing Validation ---")
        db.table("dish_ingredients").update({
            "can_remove": True,
            "discount_price": 1.50
        }).eq("dish_id", dish_id).eq("ingredient_id", ingredient_id).execute()

        # Place order with removed ingredient
        item = NewOrderItem(
            dish_name=dish_name,
            dish_price=dish_price,
            quantity=1,
            dish_id=dish_id,
            customization={
                "removed_ingredients": [ingredient_id]
            }
        )

        # Resolve price
        prices, rows = _resolve_ingredient_customizations([item])
        expected_price = max(0.0, dish_price - 1.50)
        resolved_price = prices[0]
        print(f"Expected resolved price: {expected_price}€")
        print(f"Resolved price from API: {resolved_price}€")
        assert abs(resolved_price - expected_price) < 0.01, f"Price mismatch: {resolved_price} vs {expected_price}"
        print("✓ Price discount verified successfully!")

        # TEST 2: Stock Deduction Bypass
        print("\n--- TEST 2: Stock Deduction Bypass Validation ---")
        stock_svc.deduct_stock_for_items([item], tenant_id)

        # Check stock of the removed ingredient (should remain unchanged)
        updated_stock = db.table("stock_items").select("current_quantity").eq("id", stock_item_id).execute().data[0]
        stock_qty_after = float(updated_stock["current_quantity"])
        print(f"Stock after deduction: {stock_qty_after} (Before: {stock_qty_before})")
        assert abs(stock_qty_after - stock_qty_before) < 0.001, "Stock for removed ingredient was incorrectly deducted!"
        print("✓ Stock for removed ingredient remained unchanged!")

        # Check stock for other default ingredients (should be decremented by 1)
        for name in other_default_names:
            s_rows = db.table("stock_items").select("current_quantity").eq("name", name).eq("tenant_id", tenant_id).execute().data
            qty_after = float(s_rows[0]["current_quantity"])
            qty_before = other_stock_befores[name]
            print(f"Stock for other default '{name}': {qty_before} -> {qty_after}")
            assert abs(qty_after - (qty_before - 1.0)) < 0.001, f"Stock for default ingredient '{name}' was not deducted!"
        print("✓ Stock for other default ingredients correctly decremented!")

        # TEST 3: Stock Restoration Bypass
        print("\n--- TEST 3: Stock Restoration Bypass Validation ---")
        stock_svc.restore_stock_for_items([item], tenant_id)

        # Check stock of the removed ingredient (should still be unchanged)
        updated_stock_restored = db.table("stock_items").select("current_quantity").eq("id", stock_item_id).execute().data[0]
        stock_qty_restored = float(updated_stock_restored["current_quantity"])
        print(f"Stock after restoration: {stock_qty_restored} (Before deduction: {stock_qty_before})")
        assert abs(stock_qty_restored - stock_qty_before) < 0.001, "Stock of removed ingredient was altered after restoration!"

        # Check stock of other default ingredients (should be restored back to original)
        for name in other_default_names:
            s_rows = db.table("stock_items").select("current_quantity").eq("name", name).eq("tenant_id", tenant_id).execute().data
            qty_restored = float(s_rows[0]["current_quantity"])
            qty_before = other_stock_befores[name]
            print(f"Stock for other default '{name}' after restoration: {qty_restored} (Before: {qty_before})")
            assert abs(qty_restored - qty_before) < 0.001, f"Stock of '{name}' was not restored correctly!"
        print("✓ Stock restoration verified successfully!")

    finally:
        # Restore configuration to original
        print("\nRestoring database configuration...")
        db.table("dish_ingredients").update({
            "can_remove": orig_can_remove,
            "discount_price": orig_discount_price
        }).eq("dish_id", dish_id).eq("ingredient_id", ingredient_id).execute()
        print("Done.")

if __name__ == "__main__":
    verify()

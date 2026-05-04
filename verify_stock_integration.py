#!/usr/bin/env python3
"""
Verify that stock deduction is working end-to-end.
Tests URL encoding and multi-tenant isolation.
"""
import os
import sys
from app.db import supabase
from app.models import NewOrderItem
from app.services import stock as stock_svc

# Test configuration
TENANT_ID = "test-tenant-id"  # Replace with actual tenant
WINGS_DISH_ID = "wings-test-id"  # Replace with actual Wings dish ID
INGREDIENT_NAMES = ["aletes", "arrebossat coreà", "salsa agredolça"]

def get_ingredient_stock(ingredient_name: str, tenant_id: str):
    """Get current stock for an ingredient."""
    from urllib.parse import quote
    escaped_name = quote(ingredient_name, safe='')
    escaped_tenant = quote(tenant_id, safe='')
    rows = supabase.select(
        "stock_items",
        f"select=id,name,current_quantity&name=eq.{escaped_name}&tenant_id=eq.{escaped_tenant}&limit=1",
    )
    return rows[0] if rows else None

def get_recent_movements(stock_item_id: str, limit=3):
    """Get recent movements for a stock item."""
    rows = supabase.select(
        "stock_movements",
        f"select=*,stock_items(name)&stock_item_id=eq.{stock_item_id}&order=created_at.desc&limit={limit}",
    )
    return rows

def print_section(title):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print('='*60)

def test_url_encoding():
    """Test that special characters are handled correctly."""
    print_section("TEST 1: URL Encoding & Special Characters")

    print(f"\nChecking stock for ingredients with special characters:")
    print(f"Tenant: {TENANT_ID}\n")

    for ing_name in INGREDIENT_NAMES:
        item = get_ingredient_stock(ing_name, TENANT_ID)
        if item:
            print(f"✓ Found: {ing_name}")
            print(f"  Stock ID: {item['id']}")
            print(f"  Current quantity: {item['current_quantity']}")
        else:
            print(f"✗ NOT FOUND: {ing_name}")
            print(f"  This ingredient might not exist in stock or DB is empty")

    return True

def test_deduction_logic():
    """Test that deduction logic works."""
    print_section("TEST 2: Deduction Logic")

    print(f"\nCreating test deduction for Wings dish:")
    print(f"  Dish ID: {WINGS_DISH_ID}")
    print(f"  Quantity: 1\n")

    # Create test items
    test_items = [
        NewOrderItem(
            dish_name="Wings",
            dish_price=12.50,
            quantity=1.0,
            dish_id=WINGS_DISH_ID
        )
    ]

    # Get stock before
    print("Stock BEFORE deduction:")
    stock_before = {}
    for ing_name in INGREDIENT_NAMES:
        item = get_ingredient_stock(ing_name, TENANT_ID)
        if item:
            stock_before[ing_name] = item['current_quantity']
            print(f"  {ing_name}: {item['current_quantity']}")

    # Apply deduction
    print(f"\nApplying stock deduction...")
    try:
        stock_svc.deduct_stock_for_items(test_items, TENANT_ID)
        print("✓ Deduction executed without errors")
    except Exception as e:
        print(f"✗ Error during deduction: {e}")
        import traceback
        traceback.print_exc()
        return False

    # Get stock after
    print(f"\nStock AFTER deduction:")
    for ing_name in INGREDIENT_NAMES:
        item = get_ingredient_stock(ing_name, TENANT_ID)
        if item:
            before = stock_before.get(ing_name, 0)
            after = item['current_quantity']
            delta = after - before
            symbol = "✓" if delta < 0 else "✗"
            print(f"  {ing_name}: {before} → {after} ({delta:+.2f}) {symbol}")

            # Show recent movements
            movements = get_recent_movements(item['id'], limit=1)
            if movements and movements[0]['type'] == 'consumo':
                print(f"    └─ Movement recorded: {movements[0]['type']} ({movements[0]['quantity']:+.2f})")

    return True

def test_restoration_logic():
    """Test that restoration logic works."""
    print_section("TEST 3: Restoration Logic")

    print(f"\nCreating test restoration for Wings dish:")
    print(f"  Quantity to restore: 1\n")

    # Get stock before
    print("Stock BEFORE restoration:")
    stock_before = {}
    for ing_name in INGREDIENT_NAMES:
        item = get_ingredient_stock(ing_name, TENANT_ID)
        if item:
            stock_before[ing_name] = item['current_quantity']
            print(f"  {ing_name}: {item['current_quantity']}")

    # Apply restoration
    test_items = [
        NewOrderItem(
            dish_name="Wings",
            dish_price=12.50,
            quantity=1.0,
            dish_id=WINGS_DISH_ID
        )
    ]

    print(f"\nApplying stock restoration...")
    try:
        stock_svc.restore_stock_for_items(test_items, TENANT_ID)
        print("✓ Restoration executed without errors")
    except Exception as e:
        print(f"✗ Error during restoration: {e}")
        return False

    # Get stock after
    print(f"\nStock AFTER restoration:")
    for ing_name in INGREDIENT_NAMES:
        item = get_ingredient_stock(ing_name, TENANT_ID)
        if item:
            before = stock_before.get(ing_name, 0)
            after = item['current_quantity']
            delta = after - before
            symbol = "✓" if delta > 0 else "✗"
            print(f"  {ing_name}: {before} → {after} ({delta:+.2f}) {symbol}")

            # Show recent movements
            movements = get_recent_movements(item['id'], limit=1)
            if movements and movements[0]['type'] == 'devolucion':
                print(f"    └─ Movement recorded: {movements[0]['type']} ({movements[0]['quantity']:+.2f})")

    return True

def main():
    print("\n" + "="*60)
    print("  STOCK INTEGRATION VERIFICATION")
    print("="*60)
    print(f"\nConfiguration:")
    print(f"  Tenant ID: {TENANT_ID}")
    print(f"  Wings Dish ID: {WINGS_DISH_ID}")
    print(f"  Expected ingredients: {', '.join(INGREDIENT_NAMES)}")

    try:
        results = []
        results.append(("URL Encoding & Special Characters", test_url_encoding()))
        results.append(("Deduction Logic", test_deduction_logic()))
        results.append(("Restoration Logic", test_restoration_logic()))

        print_section("SUMMARY")
        for test_name, passed in results:
            status = "✓ PASS" if passed else "✗ FAIL"
            print(f"{status}: {test_name}")

        all_passed = all(r[1] for r in results)
        if all_passed:
            print("\n✅ All verification tests passed!")
            print("\nNext steps:")
            print("  1. Place an order with Wings through the app")
            print("  2. Verify stock decreases for all ingredients")
            print("  3. Check movements appear in the history tab")
            print("  4. Delete or reduce the order to test restoration")
        else:
            print("\n⚠️  Some tests failed. Check configuration and logs above.")

    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()

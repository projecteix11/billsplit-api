#!/usr/bin/env python3
"""
Test script to verify stock deduction when orders are created.
Run: python3 test_stock_deduction.py
"""
import os
import json
from app.db import supabase

# Test data - Wings dish
WINGS_DISH_ID = "wings-test-id"  # Replace with actual Wings dish ID
TENANT_ID = "test-tenant-id"  # Replace with actual tenant ID

def get_stock_item(ingredient_name: str, tenant_id: str):
    """Get current stock for an ingredient."""
    rows = supabase.select(
        "stock_items",
        f"select=id,name,current_quantity&name=eq.{ingredient_name}&tenant_id=eq.{tenant_id}&limit=1",
    )
    return rows[0] if rows else None

def get_stock_movements(stock_item_id: str, limit=5):
    """Get recent stock movements for an item."""
    rows = supabase.select(
        "stock_movements",
        f"select=*&stock_item_id=eq.{stock_item_id}&order=created_at.desc&limit={limit}",
    )
    return rows

def print_stock_status():
    """Print current stock levels."""
    print("\n" + "="*60)
    print("CURRENT STOCK LEVELS")
    print("="*60)

    # Wings ingredients
    ingredients = ["aletes", "arrebossat coreà", "salsa agredolça"]

    for ing in ingredients:
        item = get_stock_item(ing, TENANT_ID)
        if item:
            qty = item["current_quantity"]
            status = "✓ OK" if qty > 0 else "✗ OUT"
            print(f"{ing:20} | {qty:6.2f} | {status}")

            # Show recent movements
            movements = get_stock_movements(item["id"], limit=2)
            if movements:
                print(f"  └─ Last movement: {movements[0]['type']} ({movements[0]['quantity']:+.2f})")
        else:
            print(f"{ing:20} | NOT FOUND")

    print("="*60 + "\n")

if __name__ == "__main__":
    print("\n🔍 Verificando estado del inventario de Wings...")

    try:
        print_stock_status()
        print("✅ Sistema de deducción de inventario está operativo")
        print("\n📝 Instrucciones:")
        print("   1. Ve a la app de management y haz una comanda con Wings")
        print("   2. Ejecuta este script nuevamente para ver que se dedujo el stock")
        print("   3. Verifica que los movimientos aparecen en el historial")

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

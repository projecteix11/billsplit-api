import os
import sys
import uuid
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")

if not supabase_url or not supabase_key:
    print("Error: Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY")
    sys.exit(1)

supabase: Client = create_client(supabase_url, supabase_key)

SOURCE_TENANT_ID = "ac87c9d9-0eda-451c-b583-c59e02e2e9e6"  # Mi Restaurante

def clone_menu_to_tenants():
    print(f"Fetching source template from Mi Restaurante ({SOURCE_TENANT_ID})...")
    source_categories = supabase.table("categories").select("*").eq("tenant_id", SOURCE_TENANT_ID).order("sort_order").execute().data or []
    source_dishes = supabase.table("dishes").select("*").eq("tenant_id", SOURCE_TENANT_ID).execute().data or []
    
    source_dish_ids = [d["id"] for d in source_dishes]
    source_allergens = supabase.table("dish_allergens").select("*").in_("dish_id", source_dish_ids).execute().data or []
    source_ingredients = supabase.table("dish_ingredients").select("*").in_("dish_id", source_dish_ids).execute().data or []

    source_raw_ingredients = supabase.table("ingredients").select("*").eq("tenant_id", SOURCE_TENANT_ID).execute().data or []
    print(f"Source has {len(source_categories)} categories, {len(source_dishes)} dishes, {len(source_allergens)} allergen links, {len(source_raw_ingredients)} base ingredients, {len(source_ingredients)} dish ingredient links.")

    all_tenants = supabase.table("tenants").select("id,slug,name").execute().data or []
    target_tenants = [t for t in all_tenants if t["id"] != SOURCE_TENANT_ID]

    for target in target_tenants:
        target_id = target["id"]
        slug = target.get("slug")
        name = target.get("name")
        print(f"\n--- Cloning full rich menu to '{name}' ({slug}) [{target_id}] ---")

        # 1. Clean up existing old dishes and categories for this tenant
        existing_dishes = supabase.table("dishes").select("id").eq("tenant_id", target_id).execute().data or []
        if existing_dishes:
            e_ids = [d["id"] for d in existing_dishes]
            print(f"  Cleaning {len(e_ids)} old dishes...")
            supabase.table("dish_allergens").delete().in_("dish_id", e_ids).execute()
            supabase.table("dish_ingredients").delete().in_("dish_id", e_ids).execute()
            supabase.table("dishes").delete().eq("tenant_id", target_id).execute()

        existing_categories = supabase.table("categories").select("id").eq("tenant_id", target_id).execute().data or []
        if existing_categories:
            print(f"  Cleaning {len(existing_categories)} old categories...")
            supabase.table("categories").delete().eq("tenant_id", target_id).execute()

        existing_ingredients = supabase.table("ingredients").select("id").eq("tenant_id", target_id).execute().data or []
        if existing_ingredients:
            ing_ids = [ing["id"] for ing in existing_ingredients]
            supabase.table("dish_ingredients").delete().in_("ingredient_id", ing_ids).execute()
            supabase.table("ingredients").delete().eq("tenant_id", target_id).execute()

        # 2. Clone categories with new independent UUIDs
        category_id_map = {}
        new_categories = []
        for cat in source_categories:
            new_cat_id = str(uuid.uuid4())
            category_id_map[cat["id"]] = new_cat_id
            new_categories.append({
                "id": new_cat_id,
                "tenant_id": target_id,
                "name": cat["name"],
                "sort_order": cat.get("sort_order", 0),
                "requires_kitchen": cat.get("requires_kitchen", True),
                "is_active": cat.get("is_active", True),
            })
        if new_categories:
            supabase.table("categories").insert(new_categories).execute()
            print(f"  ✅ Cloned {len(new_categories)} categories")

        # 3. Clone ingredients table for this tenant
        ingredient_id_map = {}
        new_raw_ingredients = []
        for ing in source_raw_ingredients:
            new_ing_id = str(uuid.uuid4())
            ingredient_id_map[ing["id"]] = new_ing_id
            new_raw_ingredients.append({
                "id": new_ing_id,
                "tenant_id": target_id,
                "name": ing["name"],
                "extra_price": ing.get("extra_price", 0.0),
                "description": ing.get("description"),
                "icon_url": ing.get("icon_url"),
                "img_small": ing.get("img_small"),
                "img_thumb": ing.get("img_thumb"),
                "is_active": ing.get("is_active", True),
            })
        if new_raw_ingredients:
            for i in range(0, len(new_raw_ingredients), 30):
                supabase.table("ingredients").insert(new_raw_ingredients[i:i+30]).execute()
            print(f"  ✅ Cloned {len(new_raw_ingredients)} base ingredients")

        # 4. Clone dishes with photos, full metadata and new independent UUIDs
        dish_id_map = {}
        new_dishes = []
        for dish in source_dishes:
            new_dish_id = str(uuid.uuid4())
            dish_id_map[dish["id"]] = new_dish_id
            new_cat_id = category_id_map.get(dish.get("category_id"))

            new_dishes.append({
                "id": new_dish_id,
                "tenant_id": target_id,
                "category_id": new_cat_id,
                "name": dish["name"],
                "description": dish.get("description"),
                "img_medium": dish.get("img_medium"),
                "img_small": dish.get("img_small"),
                "img_thumb": dish.get("img_thumb"),
                "img_basket": dish.get("img_basket"),
                "video_url": dish.get("video_url"),
                "price": dish.get("price", 0),
                "is_available": dish.get("is_available", True),
                "is_featured": dish.get("is_featured", False),
                "max_included_choices": dish.get("max_included_choices"),
                "max_extra_choices": dish.get("max_extra_choices"),
                "allow_takeaway": dish.get("allow_takeaway", False),
                "stock": dish.get("stock"),
                "sort_order": dish.get("sort_order", 0),
                "is_active": dish.get("is_active", True),
                "is_variable_price": dish.get("is_variable_price", False),
                "cooking_point_enabled": dish.get("cooking_point_enabled", False),
            })

        if new_dishes:
            for i in range(0, len(new_dishes), 20):
                supabase.table("dishes").insert(new_dishes[i:i+20]).execute()
            print(f"  ✅ Cloned {len(new_dishes)} dishes with photos and full details")

        # 5. Clone allergen links
        new_allergens = []
        for da in source_allergens:
            if da["dish_id"] in dish_id_map:
                new_allergens.append({
                    "dish_id": dish_id_map[da["dish_id"]],
                    "allergen_id": da["allergen_id"],
                })
        if new_allergens:
            for i in range(0, len(new_allergens), 30):
                supabase.table("dish_allergens").insert(new_allergens[i:i+30]).execute()
            print(f"  ✅ Cloned {len(new_allergens)} allergen links")

        # 6. Clone dish ingredients join
        new_dish_ingredients = []
        for di in source_ingredients:
            if di["dish_id"] in dish_id_map and di["ingredient_id"] in ingredient_id_map:
                new_dish_ingredients.append({
                    "id": str(uuid.uuid4()),
                    "dish_id": dish_id_map[di["dish_id"]],
                    "ingredient_id": ingredient_id_map[di["ingredient_id"]],
                    "present": di.get("present", True),
                    "modify": di.get("modify", False),
                    "max_quantity": di.get("max_quantity", 1),
                    "sort_order": di.get("sort_order", 0),
                    "can_remove": di.get("can_remove", False),
                    "discount_price": di.get("discount_price", 0.0),
                })
        if new_dish_ingredients:
            for i in range(0, len(new_dish_ingredients), 30):
                supabase.table("dish_ingredients").insert(new_dish_ingredients[i:i+30]).execute()
            print(f"  ✅ Cloned {len(new_dish_ingredients)} dish ingredient links")

    print("\n🎉 All restaurants now have the full rich catalog with photos, ingredients and allergens!")

if __name__ == "__main__":
    clone_menu_to_tenants()

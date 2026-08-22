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

def seed_demo_restaurant():
    slug = "demo-prepay"
    name = "Demo Pre-pagament"
    print(f"Creating / Updating tenant '{name}' ({slug})...")

    # 1. Upsert tenant
    existing = supabase.table("tenants").select("*").eq("slug", slug).execute()
    if existing.data:
        tenant_id = existing.data[0]["id"]
        print(f"Found existing tenant ID: {tenant_id}")
        supabase.table("tenants").update({
            "name": name,
            "features": {"base_module": "pre_payment", "stock": True},
            "status": "active",
        }).eq("id", tenant_id).execute()
    else:
        tenant_id = str(uuid.uuid4())
        supabase.table("tenants").insert({
            "id": tenant_id,
            "name": name,
            "slug": slug,
            "status": "active",
            "features": {"base_module": "pre_payment", "stock": True},
        }).execute()
        print(f"Created new tenant ID: {tenant_id}")

    # 2. Register module in platform_modules & restaurant_modules
    try:
        supabase.table("platform_modules").upsert([
            {"key": "pre_payment", "name": "⚡ Mòdul Base Pre-pagament", "is_core": True, "category": "core"},
            {"key": "post_payment", "name": "💳 Mòdul Base Post-pagament", "is_core": True, "category": "core"},
        ], on_conflict="key").execute()
    except Exception as e:
        print(f"platform_modules note: {e}")

    try:
        supabase.table("restaurant_modules").upsert([
            {"restaurant_id": tenant_id, "module_id": "payments"},
            {"restaurant_id": tenant_id, "module_id": "tpv"},
            {"restaurant_id": tenant_id, "module_id": "pre_payment"},
        ], on_conflict="restaurant_id,module_id").execute()
    except Exception as e:
        print(f"restaurant_modules note: {e}")

    # 3. Create Tables
    # Generate deterministic UUIDs based on table number
    table_ids = {}
    for i in range(1, 6):
        t_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"demo-prepay-table-{i}"))
        table_ids[i] = t_uuid
        supabase.table("restaurant_tables").upsert({
            "id": t_uuid,
            "number": i,
            "label": f"Taula {i}",
            "capacity": 4,
            "tenant_id": tenant_id,
            "status": "available",
            "is_active": True,
        }, on_conflict="id").execute()
    print("Tables seeded: 1..5")

    # 4. Create Categories
    cat_ids = {}
    cat_names = [
        ("Tapes i Entrants", True),
        ("Burgers i Principals", True),
        ("Postres Casolans", True),
        ("Begudes", False),
    ]
    for idx, (cname, req_kit) in enumerate(cat_names, 1):
        c_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"demo-prepay-cat-{idx}"))
        cat_ids[idx] = c_uuid
        supabase.table("categories").upsert({
            "id": c_uuid,
            "name": cname,
            "sort_order": idx,
            "tenant_id": tenant_id,
            "requires_kitchen": req_kit,
            "is_active": True,
        }, on_conflict="id").execute()
    print("Categories seeded.")

    # 5. Create Dishes
    dishes = [
        {
            "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, "demo-prepay-dish-1")),
            "name": "Braves de la Casa amb Alioli Suau",
            "description": "Patates cruixents amb salsa brava artesana i un toc d'alioli.",
            "price": 6.50,
            "category_id": cat_ids[1],
            "tenant_id": tenant_id,
            "is_available": True,
            "is_active": True,
        },
        {
            "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, "demo-prepay-dish-2")),
            "name": "Croquetes de Pernil Ibèric (4u)",
            "description": "Cremoses i cruixents, fetes amb pernil 100% ibèric.",
            "price": 7.80,
            "category_id": cat_ids[1],
            "tenant_id": tenant_id,
            "is_available": True,
            "is_active": True,
        },
        {
            "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, "demo-prepay-dish-3")),
            "name": "Burger Gourmet Smash Trufada",
            "description": "Doble carn smash de vedella madurada, formatge cheddar fos, ceba caramel·litzada i maionesa de tòfona.",
            "price": 13.90,
            "category_id": cat_ids[2],
            "tenant_id": tenant_id,
            "is_available": True,
            "is_active": True,
        },
        {
            "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, "demo-prepay-dish-4")),
            "name": "Costelles BBQ a Baixa Temperatura",
            "description": "Cuites durant 12 hores amb glassejat de salsa barbacoa fumada i patates.",
            "price": 15.50,
            "category_id": cat_ids[2],
            "tenant_id": tenant_id,
            "is_available": True,
            "is_active": True,
        },
        {
            "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, "demo-prepay-dish-5")),
            "name": "Cheesecake Cremós de Lotus",
            "description": "Pastís de formatge fluid amb base i crema de galeta Lotus Biscoff.",
            "price": 5.90,
            "category_id": cat_ids[3],
            "tenant_id": tenant_id,
            "is_available": True,
            "is_active": True,
        },
        {
            "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, "demo-prepay-dish-6")),
            "name": "Cervesa Artesana IPA 33cl",
            "description": "Cervesa d'estil IPA amb notes cítriques i afruitades.",
            "price": 3.50,
            "category_id": cat_ids[4],
            "tenant_id": tenant_id,
            "is_available": True,
            "is_active": True,
        },
        {
            "id": str(uuid.uuid5(uuid.NAMESPACE_DNS, "demo-prepay-dish-7")),
            "name": "Aigua Mineral Natural 500ml",
            "description": "Aigua mineral natural ben freda.",
            "price": 2.00,
            "category_id": cat_ids[4],
            "tenant_id": tenant_id,
            "is_available": True,
            "is_active": True,
        },
    ]
    for d in dishes:
        supabase.table("dishes").upsert(d, on_conflict="id").execute()
    print("Dishes seeded.")

    print("\n✅ Seed completed successfully!")
    print(f"Tenant: {name} (Slug: {slug})")
    print(f"Base Module: pre_payment (⚡ Mòdul Base Pre-pagament)")
    table_1_id = table_ids[1]
    print(f"Table 1 ID: {table_1_id}")
    print(f"Table 1 Diner URL: http://localhost:5174/table/{table_1_id}?num=1&tenant={slug}")

if __name__ == "__main__":
    seed_demo_restaurant()

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

STANDARD_CATEGORIES = [
    ("Tapes i Entrants", True, 1),
    ("Burgers i Principals", True, 2),
    ("Plats Combinats", True, 3),
    ("Postres Casolans", True, 4),
    ("Begudes i Refrescos", False, 5),
    ("Cafès i Infusions", False, 6),
]

STANDARD_DISHES = [
    {
        "cat_idx": 0,
        "name": "Braves de la Casa amb Alioli i Salsa Picant",
        "description": "Patates tallades a mà, cruixents per fora i toves per dins, amb el nostre alioli artesà i salsa brava secreta.",
        "price": 5.90,
    },
    {
        "cat_idx": 0,
        "name": "Croquetes Casolanes de Pernil Ibèric (4u)",
        "description": "Elaborades diàriament amb llet fresca i pernil 100% ibèric de gla.",
        "price": 6.80,
    },
    {
        "cat_idx": 0,
        "name": "Calamars a la Romana amb Llimona",
        "description": "Anelles de calamar fresc arrebossades amb farina fina i fregides al punt.",
        "price": 9.50,
    },
    {
        "cat_idx": 0,
        "name": "Pebrots del Padró amb Sal Maldon",
        "description": "Pebrots verds fregits amb oli d'oliva verge extra i escates de sal Maldon.",
        "price": 5.50,
    },
    {
        "cat_idx": 1,
        "name": "Burger Clàssica de Vedella amb Formatge",
        "description": "180g de vedella del Pirineu, formatge cheddar fos, enciam fresc, tomàquet i salsa de la casa.",
        "price": 10.90,
    },
    {
        "cat_idx": 1,
        "name": "Burger Gourmet Smash amb Ceba Caramel·litzada i Tòfona",
        "description": "Doble smash burger de vedella madurada, cheddar madurat, ceba caramel·litzada i maionesa de tòfona negra.",
        "price": 13.50,
    },
    {
        "cat_idx": 1,
        "name": "Entrecot de Vedella a la Brasa amb Patates (300g)",
        "description": "Sucós tall de carn madurada a la brasa acompanyat de patates fregides i pebrots.",
        "price": 18.90,
    },
    {
        "cat_idx": 2,
        "name": "Plat Combinat 1: Pit de pollastre, ous ferrats i patates",
        "description": "Pit de pollastre a la planxa, dos ous ferrats de pagès i guarnició de patates.",
        "price": 9.90,
    },
    {
        "cat_idx": 2,
        "name": "Plat Combinat 2: Llom adobat, amanida mixta i croquetes",
        "description": "Llom adobat a la planxa amb dues croquetes casolanes i amanida fresca.",
        "price": 10.50,
    },
    {
        "cat_idx": 3,
        "name": "Cheesecake Cremós Casolà de Lotus",
        "description": "Pastís de formatge al forn amb cor fluid i salsa de galeta Lotus Biscoff.",
        "price": 5.50,
    },
    {
        "cat_idx": 3,
        "name": "Crema Catalana Cremada a l'Estil Tradicional",
        "description": "Crema d'ou i llet aromatitzada amb canyella i llimona, amb capa de sucre cremat al moment.",
        "price": 4.90,
    },
    {
        "cat_idx": 4,
        "name": "Canya de Cervesa Estrella Damm 33cl",
        "description": "Cervesa de barril ben tirada i molt freda.",
        "price": 2.50,
    },
    {
        "cat_idx": 4,
        "name": "Coca-Cola Original 33cl",
        "description": "Refresc en ampolla de vidre.",
        "price": 2.40,
    },
    {
        "cat_idx": 4,
        "name": "Aigua Mineral Natural 500ml",
        "description": "Aigua mineral natural.",
        "price": 1.80,
    },
    {
        "cat_idx": 5,
        "name": "Cafè Sol / Cafè amb Llet",
        "description": "Cafè 100% aràbica torrat artesanalment.",
        "price": 1.50,
    },
]

def seed_all_tenants():
    print("Fetching all tenants...")
    tenants = supabase.table("tenants").select("*").execute().data or []

    for t in tenants:
        tid = t["id"]
        slug = t.get("slug") or t.get("name", "").lower().replace(" ", "-")
        name = t.get("name")
        print(f"\n--- Processing '{name}' ({slug}) [{tid}] ---")

        # 1. Ensure tenant features & status
        features = t.get("features") or {}
        base_mod = features.get("base_module") or "post_payment"
        features["base_module"] = base_mod
        supabase.table("tenants").update({
            "is_active": True,
            "status": "active" if t.get("status") == "active" else "trial",
            "features": features,
            "branding": t.get("branding") or {
                "primaryColor": "#f97316",
                "tagline": f"Benvingut a {name}",
                "coverImage": "",
                "phone": "",
                "email": "",
                "address": "",
                "socialLinks": {"instagram": "", "facebook": ""},
            },
        }).eq("id", tid).execute()

        # 2. Ensure core modules
        try:
            supabase.table("restaurant_modules").upsert([
                {"restaurant_id": tid, "module_id": "payments"},
                {"restaurant_id": tid, "module_id": "tpv"},
                {"restaurant_id": tid, "module_id": base_mod},
            ], on_conflict="restaurant_id,module_id").execute()
        except Exception as e:
            print(f"  Note restaurant_modules: {e}")

        # 3. Ensure tables (1..6)
        existing_tables = supabase.table("restaurant_tables").select("id").eq("tenant_id", tid).execute().data or []
        if len(existing_tables) < 6:
            print(f"  Seeding tables for {slug}...")
            for i in range(1, 7):
                t_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{slug}-table-{i}"))
                supabase.table("restaurant_tables").upsert({
                    "id": t_uuid,
                    "number": i,
                    "label": f"Taula {i}",
                    "capacity": 4,
                    "tenant_id": tid,
                    "status": "available",
                    "is_active": True,
                }, on_conflict="id").execute()

        # 4. Check categories & dishes
        existing_dishes = supabase.table("dishes").select("id").eq("tenant_id", tid).execute().data or []
        if len(existing_dishes) == 0:
            print(f"  Seeding categories and dishes for {slug}...")
            cat_map = {}
            for cname, req_kit, sorder in STANDARD_CATEGORIES:
                c_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{slug}-cat-{sorder}"))
                cat_map[sorder - 1] = c_uuid
                supabase.table("categories").upsert({
                    "id": c_uuid,
                    "name": cname,
                    "sort_order": sorder,
                    "tenant_id": tid,
                    "requires_kitchen": req_kit,
                    "is_active": True,
                }, on_conflict="id").execute()

            for d_idx, d_info in enumerate(STANDARD_DISHES, 1):
                d_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{slug}-dish-{d_idx}"))
                cat_id = cat_map.get(d_info["cat_idx"])
                supabase.table("dishes").upsert({
                    "id": d_uuid,
                    "name": d_info["name"],
                    "description": d_info["description"],
                    "price": d_info["price"],
                    "category_id": cat_id,
                    "tenant_id": tid,
                    "is_available": True,
                    "is_active": True,
                }, on_conflict="id").execute()
            print(f"  ✅ Seeded {len(STANDARD_DISHES)} dishes for {slug}")
        else:
            print(f"  Has {len(existing_dishes)} existing dishes.")

    print("\n🎉 All tenants are now populated and ready!")

if __name__ == "__main__":
    seed_all_tenants()

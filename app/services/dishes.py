from __future__ import annotations

import re

from app.db.supabase import get_client
from app.models import (
    Allergen,
    CreateAllergenBody,
    CreateCustomDishBody,
    CreateDishBody,
    CreateDishIngredientBody,
    CustomDish,
    DishCategory,
    DishFull,
    DishIngredient,
    UpdateDishBody,
    UpdateDishIngredientBody,
)

# ── PostgREST select with nested joins ─────────────────────────────────────

_DISH_SELECT = (
    "*"
    ",allergens:dish_allergens(allergen:allergens(id,name,icon))"
    ",ingredients:dish_ingredients(id,ingredient_id,present,sort_order,can_remove,discount_price"
    ",ingredient:ingredients(id,name,extra_price))"
)


# ── Dishes ──────────────────────────────────────────────────────────────────


def get_dishes(tenant_id: str) -> list[DishFull]:
    rows = (
        get_client().table("dishes")
        .select(_DISH_SELECT)
        .eq("tenant_id", tenant_id)
        .eq("is_available", True)
        .order("sort_order")
        .order("name")
        .execute()
        .data or []
    )
    return [_parse_dish_full(row) for row in rows]


def get_all_dishes(tenant_id: str) -> list[DishFull]:
    """All dishes including unavailable (for management)."""
    rows = (
        get_client().table("dishes")
        .select(_DISH_SELECT)
        .eq("tenant_id", tenant_id)
        .order("sort_order")
        .order("name")
        .execute()
        .data or []
    )
    return [_parse_dish_full(row) for row in rows]


def get_dish_by_id(dish_id: str, tenant_id: str | None = None) -> DishFull | None:
    query = get_client().table("dishes").select(_DISH_SELECT).eq("id", dish_id)
    if tenant_id:
        query = query.eq("tenant_id", tenant_id)
    rows = query.limit(1).execute().data or []
    if not rows:
        return None
    return _parse_dish_full(rows[0])


def create_dish(body: CreateDishBody, tenant_id: str) -> DishFull:
    data = body.model_dump(exclude_none=True)
    # Map API field → DB field
    if "image" in data:
        data["img_medium"] = data.pop("image")
    data["tenant_id"] = tenant_id
    inserted = get_client().table("dishes").insert(data).execute().data
    if not inserted:
        raise RuntimeError("failed to create dish")
    dish = get_dish_by_id(inserted[0]["id"], tenant_id)
    if not dish:
        raise RuntimeError("failed to read created dish")
    return dish


def _assert_dish_owner(dish_id: str, tenant_id: str) -> None:
    rows = (
        get_client().table("dishes")
        .select("id")
        .eq("id", dish_id)
        .eq("tenant_id", tenant_id)
        .limit(1)
        .execute()
        .data or []
    )
    if not rows:
        raise ValueError(f"dish {dish_id} not found")


def update_dish(dish_id: str, body: UpdateDishBody, tenant_id: str) -> None:
    _assert_dish_owner(dish_id, tenant_id)
    data = body.model_dump(exclude_none=True)
    # Map API field → DB field
    if "image" in data:
        data["img_medium"] = data.pop("image")
    if not data:
        return
    get_client().table("dishes").update(data).eq("id", dish_id).execute()


def delete_dish(dish_id: str, tenant_id: str) -> None:
    _assert_dish_owner(dish_id, tenant_id)
    get_client().table("dishes").delete().eq("id", dish_id).execute()


# ── Categories ──────────────────────────────────────────────────────────────


def get_categories(tenant_id: str) -> list[DishCategory]:
    rows = (
        get_client().table("categories")
        .select("id,name,sort_order,requires_kitchen")
        .eq("tenant_id", tenant_id)
        .eq("is_active", True)
        .order("sort_order")
        .execute()
        .data or []
    )
    return [DishCategory(**row) for row in rows]


def create_category(name: str, sort_order: int, tenant_id: str, requires_kitchen: bool = True) -> DishCategory:
    inserted = (
        get_client().table("categories")
        .insert({"name": name, "sort_order": sort_order, "is_active": True, "tenant_id": tenant_id, "requires_kitchen": requires_kitchen})
        .execute()
        .data
    )
    if not inserted:
        raise RuntimeError("failed to create category")
    return DishCategory(**{k: inserted[0][k] for k in ("id", "name", "sort_order", "requires_kitchen")})


def _assert_category_owner(category_id: str, tenant_id: str) -> None:
    rows = (
        get_client().table("categories")
        .select("id")
        .eq("id", category_id)
        .eq("tenant_id", tenant_id)
        .limit(1)
        .execute()
        .data or []
    )
    if not rows:
        raise ValueError(f"category {category_id} not found")


def update_category(category_id: str, name: str | None, sort_order: int | None, requires_kitchen: bool | None, tenant_id: str) -> None:
    _assert_category_owner(category_id, tenant_id)
    data: dict = {}
    if name is not None:
        data["name"] = name
    if sort_order is not None:
        data["sort_order"] = sort_order
    if requires_kitchen is not None:
        data["requires_kitchen"] = requires_kitchen
    if data:
        get_client().table("categories").update(data).eq("id", category_id).execute()


def delete_category(category_id: str, tenant_id: str) -> None:
    _assert_category_owner(category_id, tenant_id)
    get_client().table("categories").update({"is_active": False}).eq("id", category_id).execute()


# ── Allergens ───────────────────────────────────────────────────────────────


def get_allergens() -> list[Allergen]:
    rows = (
        get_client().table("allergens")
        .select("id,name,icon")
        .order("name")
        .execute()
        .data or []
    )
    return [Allergen(**row) for row in rows]


def update_allergen(allergen_id: str, name: str | None, icon: str | None) -> None:
    patch = {}
    if name is not None:
        patch["name"] = name
    if icon is not None:
        patch["icon"] = icon
    if patch:
        get_client().table("allergens").update(patch).eq("id", allergen_id).execute()


def delete_allergen(allergen_id: str) -> None:
    get_client().table("allergens").delete().eq("id", allergen_id).execute()


def create_allergen(body: CreateAllergenBody) -> Allergen:
    data = body.model_dump(exclude_none=True)
    # Generate slug from name (DB requires it)
    data["slug"] = re.sub(r"[^a-z0-9]+", "-", data["name"].lower()).strip("-")
    inserted = get_client().table("allergens").insert(data).execute().data
    if not inserted:
        raise RuntimeError("failed to create allergen")
    row = inserted[0]
    return Allergen(id=row["id"], name=row["name"], icon=row.get("icon"))


def set_dish_allergens(dish_id: str, allergen_ids: list[str], tenant_id: str) -> None:
    """Replace all allergens for a dish."""
    _assert_dish_owner(dish_id, tenant_id)
    get_client().table("dish_allergens").delete().eq("dish_id", dish_id).execute()
    if allergen_ids:
        rows = [{"dish_id": dish_id, "allergen_id": aid} for aid in allergen_ids]
        get_client().table("dish_allergens").insert(rows).execute()


# ── Dish ingredients ────────────────────────────────────────────────────────
# Real schema: master `ingredients` table + `dish_ingredients` junction.
# API exposes a flat DishIngredient to the frontend.


def get_dish_ingredients(dish_id: str) -> list[DishIngredient]:
    rows = (
        get_client().table("dish_ingredients")
        .select("id,ingredient_id,present,sort_order,can_remove,discount_price,ingredient:ingredients(id,name,extra_price)")
        .eq("dish_id", dish_id)
        .order("sort_order")
        .execute()
        .data or []
    )
    result = []
    for row in rows:
        ing = row.get("ingredient")
        if not ing:
            continue
        result.append(DishIngredient(
            id=ing["id"],
            dish_id=dish_id,
            name=ing["name"],
            is_default=row.get("present", True),
            extra_price=float(ing.get("extra_price", 0)),
            sort_order=row.get("sort_order", 0),
            can_remove=row.get("can_remove", False),
            discount_price=float(row.get("discount_price", 0)),
        ))
    return result


def create_dish_ingredient(dish_id: str, body: CreateDishIngredientBody, tenant_id: str) -> DishIngredient:
    # Create ingredient in master table
    ing_data = {
        "tenant_id": tenant_id,
        "name": body.name,
        "extra_price": body.extra_price,
    }
    inserted = get_client().table("ingredients").insert(ing_data).execute().data
    if not inserted:
        raise RuntimeError("failed to create ingredient")
    ingredient_id = inserted[0]["id"]

    # Create junction row
    junction = {
        "dish_id": dish_id,
        "ingredient_id": ingredient_id,
        "present": body.is_default,
        "sort_order": body.sort_order,
        "can_remove": body.can_remove,
        "discount_price": body.discount_price,
    }
    get_client().table("dish_ingredients").insert(junction).execute()

    return DishIngredient(
        id=ingredient_id,
        dish_id=dish_id,
        name=body.name,
        is_default=body.is_default,
        extra_price=body.extra_price,
        sort_order=body.sort_order,
        can_remove=body.can_remove,
        discount_price=body.discount_price,
    )


def update_dish_ingredient(
    dish_id: str, ingredient_id: str, body: UpdateDishIngredientBody, tenant_id: str
) -> None:
    _assert_dish_owner(dish_id, tenant_id)
    updates = body.model_dump(exclude_none=True)
    if not updates:
        return

    # Split: name/extra_price → ingredients table, is_default/sort_order → junction
    ing_updates: dict = {}
    junction_updates: dict = {}

    if "name" in updates:
        ing_updates["name"] = updates["name"]
    if "extra_price" in updates:
        ing_updates["extra_price"] = updates["extra_price"]
    if "is_default" in updates:
        junction_updates["present"] = updates["is_default"]
    if "sort_order" in updates:
        junction_updates["sort_order"] = updates["sort_order"]
    if "can_remove" in updates:
        junction_updates["can_remove"] = updates["can_remove"]
    if "discount_price" in updates:
        junction_updates["discount_price"] = updates["discount_price"]

    if ing_updates:
        get_client().table("ingredients").update(ing_updates).eq("id", ingredient_id).execute()
    if junction_updates:
        get_client().table("dish_ingredients").update(junction_updates).eq("dish_id", dish_id).eq("ingredient_id", ingredient_id).execute()


def delete_dish_ingredient(dish_id: str, ingredient_id: str, tenant_id: str) -> None:
    """Remove ingredient from dish (junction only)."""
    _assert_dish_owner(dish_id, tenant_id)
    get_client().table("dish_ingredients").delete().eq("dish_id", dish_id).eq("ingredient_id", ingredient_id).execute()


# ── Custom dishes ───────────────────────────────────────────────────────────


def get_custom_dishes_for_table(table_id: str) -> list[CustomDish]:
    rows = (
        get_client().table("custom_dishes")
        .select("*")
        .eq("table_id", table_id)
        .order("created_at", desc=True)
        .execute()
        .data or []
    )
    return [CustomDish(**row) for row in rows]


def create_custom_dish(body: CreateCustomDishBody, user_id: str) -> CustomDish:
    row = body.model_dump(exclude_none=True)
    row["created_by"] = user_id
    inserted = get_client().table("custom_dishes").insert(row).execute().data
    if not inserted:
        raise RuntimeError("failed to create custom dish")
    return CustomDish(**inserted[0])


def delete_custom_dish(custom_dish_id: str) -> None:
    get_client().table("custom_dishes").delete().eq("id", custom_dish_id).execute()


def delete_custom_dishes_for_table(table_id: str) -> None:
    get_client().table("custom_dishes").delete().eq("table_id", table_id).execute()


# ── Helpers ─────────────────────────────────────────────────────────────────


def _parse_dish_full(row: dict) -> DishFull:
    """Parse a dish row with nested allergens and ingredients from PostgREST."""
    # ── Allergens (via dish_allergens → allergens) ──
    raw_allergens = row.pop("allergens", []) or []
    allergens = []
    for entry in raw_allergens:
        if isinstance(entry, dict) and "allergen" in entry and entry["allergen"]:
            allergens.append(Allergen(**entry["allergen"]))

    # ── Ingredients (via dish_ingredients → ingredients) ──
    raw_ingredients = row.pop("ingredients", []) or []
    ingredients = []
    for entry in raw_ingredients:
        if not isinstance(entry, dict):
            continue
        ing = entry.get("ingredient")
        if not ing:
            continue
        ingredients.append(DishIngredient(
            id=ing["id"],
            dish_id=row["id"],
            name=ing["name"],
            is_default=entry.get("present", True),
            extra_price=float(ing.get("extra_price", 0)),
            sort_order=entry.get("sort_order", 0),
            can_remove=entry.get("can_remove", False),
            discount_price=float(entry.get("discount_price", 0)),
        ))

    # ── Map image: prefer img_medium, fallback to img_small ──
    image = row.pop("img_medium", None) or row.pop("img_small", None)

    # ── Remove DB-only fields not in Dish model ──
    for key in [
        "tenant_id", "img_small", "img_medium", "img_thumb", "img_basket",
        "allow_takeaway", "stock", "sort_order", "is_active",
    ]:
        row.pop(key, None)

    return DishFull(**row, image=image, allergens=allergens, ingredients=ingredients)

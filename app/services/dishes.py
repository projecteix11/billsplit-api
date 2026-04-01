from __future__ import annotations

import re

from app.db import supabase
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

# ── Tenant helper ──────────────────────────────────────────────────────────

_cached_tenant_id: str | None = None

_FALLBACK_TENANT_ID = "ac87c9d9-0eda-451c-b583-c59e02e2e9e6"


def _get_tenant_id() -> str:
    """Get tenant_id from an existing dish, or fall back to default tenant."""
    global _cached_tenant_id
    if _cached_tenant_id:
        return _cached_tenant_id
    rows = supabase.select("dishes", "select=tenant_id&limit=1")
    if rows:
        _cached_tenant_id = rows[0]["tenant_id"]
        return _cached_tenant_id
    # Empty DB — use fallback tenant
    _cached_tenant_id = _FALLBACK_TENANT_ID
    return _cached_tenant_id


# ── PostgREST select with nested joins ─────────────────────────────────────

_DISH_SELECT = (
    "select=*"
    ",allergens:dish_allergens(allergen:allergens(id,name,icon))"
    ",ingredients:dish_ingredients(id,ingredient_id,present,sort_order"
    ",ingredient:ingredients(id,name,extra_price))"
)


# ── Dishes ──────────────────────────────────────────────────────────────────


def get_dishes() -> list[DishFull]:
    rows = supabase.select(
        "dishes",
        f"{_DISH_SELECT}&is_available=eq.true&order=sort_order,name",
    )
    return [_parse_dish_full(row) for row in rows]


def get_all_dishes() -> list[DishFull]:
    """All dishes including unavailable (for management)."""
    rows = supabase.select(
        "dishes",
        f"{_DISH_SELECT}&order=sort_order,name",
    )
    return [_parse_dish_full(row) for row in rows]


def get_dish_by_id(dish_id: str) -> DishFull | None:
    rows = supabase.select(
        "dishes",
        f"{_DISH_SELECT}&id=eq.{dish_id}&limit=1",
    )
    if not rows:
        return None
    return _parse_dish_full(rows[0])


def create_dish(body: CreateDishBody) -> DishFull:
    data = body.model_dump(exclude_none=True)
    # Map API field → DB field
    if "image" in data:
        data["img_medium"] = data.pop("image")
    data["tenant_id"] = _get_tenant_id()
    inserted = supabase.insert("dishes", data, return_result=True)
    if not inserted:
        raise RuntimeError("failed to create dish")
    dish = get_dish_by_id(inserted[0]["id"])
    if not dish:
        raise RuntimeError("failed to read created dish")
    return dish


def update_dish(dish_id: str, body: UpdateDishBody) -> None:
    data = body.model_dump(exclude_none=True)
    # Map API field → DB field
    if "image" in data:
        data["img_medium"] = data.pop("image")
    if not data:
        return
    supabase.update("dishes", f"id=eq.{dish_id}", data)


def delete_dish(dish_id: str) -> None:
    supabase.delete("dishes", f"id=eq.{dish_id}")


# ── Categories ──────────────────────────────────────────────────────────────


def get_categories() -> list[DishCategory]:
    rows = supabase.select(
        "categories",
        "select=id,name,sort_order,requires_kitchen&is_active=eq.true&order=sort_order",
    )
    return [DishCategory(**row) for row in rows]


def create_category(name: str, sort_order: int, requires_kitchen: bool = True) -> DishCategory:
    tenant_id = _get_tenant_id()
    inserted = supabase.insert(
        "categories",
        {"name": name, "sort_order": sort_order, "is_active": True, "tenant_id": tenant_id, "requires_kitchen": requires_kitchen},
        return_result=True,
    )
    if not inserted:
        raise RuntimeError("failed to create category")
    return DishCategory(**{k: inserted[0][k] for k in ("id", "name", "sort_order", "requires_kitchen")})


def update_category(category_id: str, name: str | None, sort_order: int | None, requires_kitchen: bool | None = None) -> None:
    data: dict = {}
    if name is not None:
        data["name"] = name
    if sort_order is not None:
        data["sort_order"] = sort_order
    if requires_kitchen is not None:
        data["requires_kitchen"] = requires_kitchen
    if data:
        supabase.update("categories", f"id=eq.{category_id}", data)


def delete_category(category_id: str) -> None:
    supabase.update("categories", f"id=eq.{category_id}", {"is_active": False})


# ── Allergens ───────────────────────────────────────────────────────────────


def get_allergens() -> list[Allergen]:
    rows = supabase.select("allergens", "select=id,name,icon&order=name")
    return [Allergen(**row) for row in rows]


def update_allergen(allergen_id: str, name: str | None, icon: str | None) -> None:
    patch = {}
    if name is not None:
        patch["name"] = name
    if icon is not None:
        patch["icon"] = icon
    if patch:
        supabase.update("allergens", f"id=eq.{allergen_id}", patch)


def delete_allergen(allergen_id: str) -> None:
    supabase.delete("allergens", f"id=eq.{allergen_id}")


def create_allergen(body: CreateAllergenBody) -> Allergen:
    data = body.model_dump(exclude_none=True)
    # Generate slug from name (DB requires it)
    data["slug"] = re.sub(r"[^a-z0-9]+", "-", data["name"].lower()).strip("-")
    inserted = supabase.insert("allergens", data, return_result=True)
    if not inserted:
        raise RuntimeError("failed to create allergen")
    row = inserted[0]
    return Allergen(id=row["id"], name=row["name"], icon=row.get("icon"))


def set_dish_allergens(dish_id: str, allergen_ids: list[str]) -> None:
    """Replace all allergens for a dish."""
    supabase.delete("dish_allergens", f"dish_id=eq.{dish_id}")
    if allergen_ids:
        rows = [{"dish_id": dish_id, "allergen_id": aid} for aid in allergen_ids]
        supabase.insert("dish_allergens", rows, return_result=False)


# ── Dish ingredients ────────────────────────────────────────────────────────
# Real schema: master `ingredients` table + `dish_ingredients` junction.
# API exposes a flat DishIngredient to the frontend.


def get_dish_ingredients(dish_id: str) -> list[DishIngredient]:
    rows = supabase.select(
        "dish_ingredients",
        f"select=id,ingredient_id,present,sort_order"
        f",ingredient:ingredients(id,name,extra_price)"
        f"&dish_id=eq.{dish_id}&order=sort_order",
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
        ))
    return result


def create_dish_ingredient(dish_id: str, body: CreateDishIngredientBody) -> DishIngredient:
    tenant_id = _get_tenant_id()
    # Create ingredient in master table
    ing_data = {
        "tenant_id": tenant_id,
        "name": body.name,
        "extra_price": body.extra_price,
    }
    inserted = supabase.insert("ingredients", ing_data, return_result=True)
    if not inserted:
        raise RuntimeError("failed to create ingredient")
    ingredient_id = inserted[0]["id"]

    # Create junction row
    junction = {
        "dish_id": dish_id,
        "ingredient_id": ingredient_id,
        "present": body.is_default,
        "sort_order": body.sort_order,
    }
    supabase.insert("dish_ingredients", junction, return_result=False)

    return DishIngredient(
        id=ingredient_id,
        dish_id=dish_id,
        name=body.name,
        is_default=body.is_default,
        extra_price=body.extra_price,
        sort_order=body.sort_order,
    )


def update_dish_ingredient(
    dish_id: str, ingredient_id: str, body: UpdateDishIngredientBody
) -> None:
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

    if ing_updates:
        supabase.update("ingredients", f"id=eq.{ingredient_id}", ing_updates)
    if junction_updates:
        supabase.update(
            "dish_ingredients",
            f"dish_id=eq.{dish_id}&ingredient_id=eq.{ingredient_id}",
            junction_updates,
        )


def delete_dish_ingredient(dish_id: str, ingredient_id: str) -> None:
    """Remove ingredient from dish (junction only)."""
    supabase.delete(
        "dish_ingredients",
        f"dish_id=eq.{dish_id}&ingredient_id=eq.{ingredient_id}",
    )


# ── Custom dishes ───────────────────────────────────────────────────────────


def get_custom_dishes_for_table(table_id: str) -> list[CustomDish]:
    rows = supabase.select(
        "custom_dishes",
        f"table_id=eq.{table_id}&order=created_at.desc",
    )
    return [CustomDish(**row) for row in rows]


def create_custom_dish(body: CreateCustomDishBody, user_id: str) -> CustomDish:
    row = body.model_dump(exclude_none=True)
    row["created_by"] = user_id
    inserted = supabase.insert("custom_dishes", row, return_result=True)
    if not inserted:
        raise RuntimeError("failed to create custom dish")
    return CustomDish(**inserted[0])


def delete_custom_dish(custom_dish_id: str) -> None:
    supabase.delete("custom_dishes", f"id=eq.{custom_dish_id}")


def delete_custom_dishes_for_table(table_id: str) -> None:
    supabase.delete("custom_dishes", f"table_id=eq.{table_id}")


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
        ))

    # ── Map image: prefer img_medium, fallback to img_small ──
    image = row.pop("img_medium", None) or row.pop("img_small", None)

    # ── Remove DB-only fields not in Dish model ──
    for key in [
        "tenant_id", "img_small", "img_medium", "img_thumb", "img_basket",
        "video_url", "allow_takeaway", "stock", "sort_order", "is_active",
    ]:
        row.pop(key, None)

    return DishFull(**row, image=image, allergens=allergens, ingredients=ingredients)

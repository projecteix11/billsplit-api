from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.middleware.auth import require_auth
from app.middleware.rate_limit import limiter
from app.models import (
    CreateAllergenBody,
    UpdateAllergenBody,
    CreateCategoryBody,
    UpdateCategoryBody,
    CreateDishBody,
    CreateDishIngredientBody,
    CreateCustomDishBody,
    UpdateDishBody,
    UpdateDishIngredientBody,
)
from app.services import dishes as svc

router = APIRouter()


# ── Dishes (public: available only / auth: all) ────────────────────────────


@router.get("/api/dishes")
def get_dishes(all: bool = False, _user_id: str | None = None):
    try:
        if all:
            data = svc.get_all_dishes()
        else:
            data = svc.get_dishes()
        return {"data": [d.model_dump() for d in data], "error": None}
    except Exception as e:
        return JSONResponse(status_code=500, content={"data": None, "error": str(e)})


@router.get("/api/dishes/{dish_id}")
def get_dish(dish_id: str):
    try:
        dish = svc.get_dish_by_id(dish_id)
        if dish is None:
            return JSONResponse(status_code=404, content={"data": None, "error": "Dish not found"})
        return {"data": dish.model_dump(), "error": None}
    except Exception as e:
        return JSONResponse(status_code=500, content={"data": None, "error": str(e)})


@router.post("/api/dishes", status_code=201)
@limiter.limit("20/minute")
def create_dish(request: Request, body: CreateDishBody, _user_id: str = Depends(require_auth)):
    try:
        dish = svc.create_dish(body)
        return JSONResponse(status_code=201, content={"data": dish.model_dump(), "error": None})
    except Exception as e:
        return JSONResponse(status_code=500, content={"data": None, "error": str(e)})


@router.patch("/api/dishes/{dish_id}")
@limiter.limit("20/minute")
def update_dish(request: Request, dish_id: str, body: UpdateDishBody, _user_id: str = Depends(require_auth)):
    try:
        svc.update_dish(dish_id, body)
        dish = svc.get_dish_by_id(dish_id)
        return {"data": dish.model_dump() if dish else None, "error": None}
    except Exception as e:
        return JSONResponse(status_code=500, content={"data": None, "error": str(e)})


@router.delete("/api/dishes/{dish_id}")
@limiter.limit("20/minute")
def delete_dish(request: Request, dish_id: str, _user_id: str = Depends(require_auth)):
    try:
        svc.delete_dish(dish_id)
        return {"data": None, "error": None}
    except Exception as e:
        return JSONResponse(status_code=500, content={"data": None, "error": str(e)})


# ── Categories ──────────────────────────────────────────────────────────────


@router.get("/api/categories")
def get_categories():
    try:
        data = svc.get_categories()
        return {"data": [c.model_dump() for c in data], "error": None}
    except Exception as e:
        return JSONResponse(status_code=500, content={"data": None, "error": str(e)})


@router.post("/api/categories", status_code=201)
@limiter.limit("20/minute")
def create_category(request: Request, body: CreateCategoryBody, _user_id: str = Depends(require_auth)):
    try:
        category = svc.create_category(body.name, body.sort_order or 0, body.requires_kitchen if body.requires_kitchen is not None else True)
        return JSONResponse(status_code=201, content={"data": category.model_dump(), "error": None})
    except Exception as e:
        return JSONResponse(status_code=500, content={"data": None, "error": str(e)})


@router.patch("/api/categories/{category_id}")
@limiter.limit("20/minute")
def update_category(request: Request, category_id: str, body: UpdateCategoryBody, _user_id: str = Depends(require_auth)):
    try:
        svc.update_category(category_id, body.name, body.sort_order, body.requires_kitchen)
        return {"data": None, "error": None}
    except Exception as e:
        return JSONResponse(status_code=500, content={"data": None, "error": str(e)})


@router.delete("/api/categories/{category_id}")
@limiter.limit("20/minute")
def delete_category(request: Request, category_id: str, _user_id: str = Depends(require_auth)):
    try:
        svc.delete_category(category_id)
        return {"data": None, "error": None}
    except Exception as e:
        return JSONResponse(status_code=500, content={"data": None, "error": str(e)})


# ── Allergens ───────────────────────────────────────────────────────────────


@router.get("/api/allergens")
def get_allergens():
    try:
        data = svc.get_allergens()
        return {"data": [a.model_dump() for a in data], "error": None}
    except Exception as e:
        return JSONResponse(status_code=500, content={"data": None, "error": str(e)})


@router.post("/api/allergens", status_code=201)
@limiter.limit("20/minute")
def create_allergen(request: Request, body: CreateAllergenBody, _user_id: str = Depends(require_auth)):
    try:
        allergen = svc.create_allergen(body)
        return JSONResponse(status_code=201, content={"data": allergen.model_dump(), "error": None})
    except Exception as e:
        return JSONResponse(status_code=500, content={"data": None, "error": str(e)})


@router.patch("/api/allergens/{allergen_id}")
@limiter.limit("30/minute")
def update_allergen(request: Request, allergen_id: str, body: UpdateAllergenBody, _user_id: str = Depends(require_auth)):
    try:
        svc.update_allergen(allergen_id, body.name, body.icon)
        return {"data": None, "error": None}
    except Exception as e:
        return JSONResponse(status_code=500, content={"data": None, "error": str(e)})


@router.delete("/api/allergens/{allergen_id}")
@limiter.limit("20/minute")
def delete_allergen(request: Request, allergen_id: str, _user_id: str = Depends(require_auth)):
    try:
        svc.delete_allergen(allergen_id)
        return {"data": None, "error": None}
    except Exception as e:
        return JSONResponse(status_code=500, content={"data": None, "error": str(e)})


# ── Dish allergens ──────────────────────────────────────────────────────────


class SetDishAllergensBody(BaseModel):
    allergen_ids: list[str]


@router.put("/api/dishes/{dish_id}/allergens")
@limiter.limit("20/minute")
def set_dish_allergens(
    request: Request,
    dish_id: str,
    body: SetDishAllergensBody,
    _user_id: str = Depends(require_auth),
):
    try:
        svc.set_dish_allergens(dish_id, body.allergen_ids)
        return {"data": None, "error": None}
    except Exception as e:
        return JSONResponse(status_code=500, content={"data": None, "error": str(e)})


# ── Dish ingredients ────────────────────────────────────────────────────────


@router.get("/api/dishes/{dish_id}/ingredients")
def get_dish_ingredients(dish_id: str):
    try:
        data = svc.get_dish_ingredients(dish_id)
        return {"data": [i.model_dump() for i in data], "error": None}
    except Exception as e:
        return JSONResponse(status_code=500, content={"data": None, "error": str(e)})


@router.post("/api/dishes/{dish_id}/ingredients", status_code=201)
@limiter.limit("20/minute")
def create_dish_ingredient(
    request: Request,
    dish_id: str,
    body: CreateDishIngredientBody,
    _user_id: str = Depends(require_auth),
):
    try:
        ingredient = svc.create_dish_ingredient(dish_id, body)
        return JSONResponse(status_code=201, content={"data": ingredient.model_dump(), "error": None})
    except Exception as e:
        return JSONResponse(status_code=500, content={"data": None, "error": str(e)})


@router.patch("/api/dishes/{dish_id}/ingredients/{ingredient_id}")
@limiter.limit("20/minute")
def update_dish_ingredient(
    request: Request,
    dish_id: str,
    ingredient_id: str,
    body: UpdateDishIngredientBody,
    _user_id: str = Depends(require_auth),
):
    try:
        svc.update_dish_ingredient(dish_id, ingredient_id, body)
        return {"data": None, "error": None}
    except Exception as e:
        return JSONResponse(status_code=500, content={"data": None, "error": str(e)})


@router.delete("/api/dishes/{dish_id}/ingredients/{ingredient_id}")
@limiter.limit("20/minute")
def delete_dish_ingredient(
    request: Request,
    dish_id: str,
    ingredient_id: str,
    _user_id: str = Depends(require_auth),
):
    try:
        svc.delete_dish_ingredient(dish_id, ingredient_id)
        return {"data": None, "error": None}
    except Exception as e:
        return JSONResponse(status_code=500, content={"data": None, "error": str(e)})


# ── Custom dishes ───────────────────────────────────────────────────────────


@router.get("/api/tables/{table_id}/custom-dishes")
def get_custom_dishes_for_table(table_id: str):
    try:
        data = svc.get_custom_dishes_for_table(table_id)
        return {"data": [d.model_dump() for d in data], "error": None}
    except Exception as e:
        return JSONResponse(status_code=500, content={"data": None, "error": str(e)})


@router.post("/api/custom-dishes", status_code=201)
@limiter.limit("20/minute")
def create_custom_dish(
    request: Request,
    body: CreateCustomDishBody,
    user_id: str = Depends(require_auth),
):
    try:
        dish = svc.create_custom_dish(body, user_id)
        return JSONResponse(status_code=201, content={"data": dish.model_dump(), "error": None})
    except Exception as e:
        return JSONResponse(status_code=500, content={"data": None, "error": str(e)})


@router.delete("/api/custom-dishes/{custom_dish_id}")
@limiter.limit("20/minute")
def delete_custom_dish(
    request: Request,
    custom_dish_id: str,
    _user_id: str = Depends(require_auth),
):
    try:
        svc.delete_custom_dish(custom_dish_id)
        return {"data": None, "error": None}
    except Exception as e:
        return JSONResponse(status_code=500, content={"data": None, "error": str(e)})

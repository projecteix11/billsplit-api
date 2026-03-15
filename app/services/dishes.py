from app.db import supabase
from app.models import Dish, DishCategory


def get_dishes() -> list[Dish]:
    rows = supabase.select("dishes", "is_available=eq.true&order=name")
    return [Dish(**row) for row in rows]


def get_categories() -> list[DishCategory]:
    rows = supabase.select("dish_categories", "order=sort_order")
    return [DishCategory(**row) for row in rows]

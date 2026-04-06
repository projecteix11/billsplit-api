from __future__ import annotations
from typing import Optional
from pydantic import BaseModel


# ── Dishes ──────────────────────────────────────────────────────────────────

class Dish(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    price: float
    is_available: bool
    is_featured: bool = False
    category_id: Optional[str] = None
    image: Optional[str] = None
    max_included_choices: Optional[int] = None
    max_extra_choices: Optional[int] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class DishCategory(BaseModel):
    id: str
    name: str
    sort_order: int
    requires_kitchen: bool = True


class CreateDishBody(BaseModel):
    name: str
    description: Optional[str] = None
    price: float
    category_id: Optional[str] = None
    image: Optional[str] = None
    is_featured: bool = False
    is_available: bool = True
    max_included_choices: Optional[int] = None
    max_extra_choices: Optional[int] = None


class UpdateDishBody(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = None
    category_id: Optional[str] = None
    image: Optional[str] = None
    is_featured: Optional[bool] = None
    is_available: Optional[bool] = None
    max_included_choices: Optional[int] = None
    max_extra_choices: Optional[int] = None


# ── Allergens ───────────────────────────────────────────────────────────────

class Allergen(BaseModel):
    id: str
    name: str
    icon: Optional[str] = None


class CreateCategoryBody(BaseModel):
    name: str
    sort_order: Optional[int] = 0
    requires_kitchen: Optional[bool] = True


class UpdateCategoryBody(BaseModel):
    name: Optional[str] = None
    sort_order: Optional[int] = None
    requires_kitchen: Optional[bool] = None


class CreateAllergenBody(BaseModel):
    name: str
    icon: Optional[str] = None


class UpdateAllergenBody(BaseModel):
    name: Optional[str] = None
    icon: Optional[str] = None


# ── Daily menus ────────────────────────────────────────────────────────────

class DailyMenuItem(BaseModel):
    id: str
    section_id: str
    dish_id: Optional[str] = None
    name: str
    description: Optional[str] = None
    supplement_price: float = 0
    sort_order: int = 0


class DailyMenuSection(BaseModel):
    id: str
    menu_id: str
    name: str
    sort_order: int = 0
    max_choices: int = 1
    items: list[DailyMenuItem] = []


class DailyMenu(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    price: float
    is_active: bool = True
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    sections: list[DailyMenuSection] = []


class CreateDailyMenuBody(BaseModel):
    name: str
    description: Optional[str] = None
    price: float


class UpdateDailyMenuBody(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = None
    is_active: Optional[bool] = None


class CreateDailyMenuSectionBody(BaseModel):
    name: str
    sort_order: int = 0
    max_choices: int = 1


class UpdateDailyMenuSectionBody(BaseModel):
    name: Optional[str] = None
    sort_order: Optional[int] = None
    max_choices: Optional[int] = None


class CreateDailyMenuItemBody(BaseModel):
    dish_id: Optional[str] = None
    name: str
    description: Optional[str] = None
    supplement_price: float = 0
    sort_order: int = 0


class UpdateDailyMenuItemBody(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    supplement_price: Optional[float] = None
    sort_order: Optional[int] = None


# ── Dish ingredients ────────────────────────────────────────────────────────

class DishIngredient(BaseModel):
    id: str
    dish_id: str
    name: str
    is_default: bool = True
    extra_price: float = 0
    sort_order: int = 0


class CreateDishIngredientBody(BaseModel):
    name: str
    is_default: bool = True
    extra_price: float = 0
    sort_order: int = 0


class UpdateDishIngredientBody(BaseModel):
    name: Optional[str] = None
    is_default: Optional[bool] = None
    extra_price: Optional[float] = None
    sort_order: Optional[int] = None


# ── Full dish (with relations) ──────────────────────────────────────────────

class DishFull(Dish):
    allergens: list[Allergen] = []
    ingredients: list[DishIngredient] = []


# ── Custom dishes (special requests per table) ─────────────────────────────

class CustomDish(BaseModel):
    id: str
    table_id: str
    name: str
    description: Optional[str] = None
    price: float
    notes: Optional[str] = None
    created_by: Optional[str] = None
    created_at: Optional[str] = None


class CreateCustomDishBody(BaseModel):
    table_id: str
    name: str
    description: Optional[str] = None
    price: float
    notes: Optional[str] = None


# ── Orders ──────────────────────────────────────────────────────────────────

class OrderItem(BaseModel):
    id: str
    order_id: str
    dish_name: str
    dish_price: float
    quantity: int
    notes: Optional[str] = None
    diner_name: str
    kitchen_status: Optional[str] = None
    payment_status: str
    dish_id: Optional[str] = None
    customization: Optional[dict] = None
    category_id: Optional[str] = None


class Order(BaseModel):
    id: str
    table_id: str
    table_number: int
    status: str
    subtotal: float
    tax_amount: float
    total: float
    created_at: str
    updated_at: str
    items: list[OrderItem] = []


class NewOrderItem(BaseModel):
    dish_name: str
    dish_price: float
    quantity: int
    notes: Optional[str] = None
    diner_name: Optional[str] = None
    dish_id: Optional[str] = None
    customization: Optional[dict] = None
    category_id: Optional[str] = None


class Payment(BaseModel):
    id: str
    order_id: str
    amount: float
    tip_amount: float
    total_charged: float
    payment_method: str
    status: str


# ---------------------------------------------------------------------------
# Request bodies
# ---------------------------------------------------------------------------

class CreateOrderBody(BaseModel):
    tableId: str
    tableNumber: int
    items: list[NewOrderItem]


class AddItemsBody(BaseModel):
    items: list[NewOrderItem]


class CreatePaymentBody(BaseModel):
    orderId: str
    amount: float
    method: str


class UpdateQuantityBody(BaseModel):
    quantity: int


class RedsysSignBody(BaseModel):
    amount: float
    urlOk: str
    urlKo: str


# ── Staff ──────────────────────────────────────────────────────────────────

class CreateStaffBody(BaseModel):
    email: str
    password: str
    firstName: str
    lastName: str
    role: str
    tenantId: str


class DeleteStaffBody(BaseModel):
    tenantId: str

from __future__ import annotations
from typing import Any, Optional
from pydantic import BaseModel, Field


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
    video_url: Optional[str] = None
    max_included_choices: Optional[int] = None
    max_extra_choices: Optional[int] = None
    is_variable_price: bool = False
    cooking_point_enabled: bool = False
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
    is_variable_price: bool = False
    max_included_choices: Optional[int] = None
    max_extra_choices: Optional[int] = None
    cooking_point_enabled: Optional[bool] = None


class UpdateDishBody(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = None
    category_id: Optional[str] = None
    image: Optional[str] = None
    is_featured: Optional[bool] = None
    is_available: Optional[bool] = None
    is_variable_price: Optional[bool] = None
    max_included_choices: Optional[int] = None
    max_extra_choices: Optional[int] = None
    cooking_point_enabled: Optional[bool] = None


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
    allow_two_first_courses: bool = False
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    sections: list[DailyMenuSection] = []
    schedule_restriction: Optional[dict] = None


class CreateDailyMenuBody(BaseModel):
    name: str
    description: Optional[str] = None
    price: float
    allow_two_first_courses: Optional[bool] = False
    schedule_restriction: Optional[dict] = None


class UpdateDailyMenuBody(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = None
    is_active: Optional[bool] = None
    allow_two_first_courses: Optional[bool] = None
    schedule_restriction: Optional[dict] = None


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
    can_remove: bool = False
    discount_price: float = 0


class CreateDishIngredientBody(BaseModel):
    name: str
    is_default: bool = True
    extra_price: float = 0
    sort_order: int = 0
    can_remove: bool = False
    discount_price: float = 0


class UpdateDishIngredientBody(BaseModel):
    name: Optional[str] = None
    is_default: Optional[bool] = None
    extra_price: Optional[float] = None
    sort_order: Optional[int] = None
    can_remove: Optional[bool] = None
    discount_price: Optional[float] = None


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
    split_portions: int = 1
    paid_portions: int = 0
    dish_id: Optional[str] = None
    customization: Optional[dict] = None
    category_id: Optional[str] = None
    original_price: Optional[float] = None
    price_override_reason: Optional[str] = None
    source: str = "management"


class Order(BaseModel):
    id: str
    table_id: str
    table_number: int
    table_label: Optional[str] = None
    status: str
    subtotal: float
    tax_amount: float
    total: float
    created_at: str
    updated_at: str
    items: list[OrderItem] = []
    tenant_id: Optional[str] = None


class NewOrderItem(BaseModel):
    dish_name: str
    dish_price: float
    quantity: int
    notes: Optional[str] = None
    diner_name: Optional[str] = None
    dish_id: Optional[str] = None
    customization: Optional[dict] = None
    category_id: Optional[str] = None
    original_price: Optional[float] = None
    price_override_reason: Optional[str] = None
    source: Optional[str] = None


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
    coveredItems: Optional[list[RedsysInitiateItem]] = None


class PrePayCheckoutBody(BaseModel):
    tableId: str
    tableNumber: int
    items: list[NewOrderItem]
    paymentMethod: str = "card"
    dinerName: Optional[str] = "Comensal"
    customerEmail: Optional[str] = None
    customerPhone: Optional[str] = None
    notes: Optional[str] = None
    trackingCode: Optional[str] = None


class PrePayCheckoutResponse(BaseModel):
    order: Order
    tracking_code: str
    tracking_url: str
    payment_id: Optional[str] = None


class OrderTrackingResponse(BaseModel):
    order_id: str
    tracking_code: str
    table_id: str
    table_number: int
    table_label: Optional[str] = None
    status: str
    subtotal: float
    tax_amount: float
    total: float
    amount_paid: float
    created_at: str
    updated_at: str
    tenant_name: Optional[str] = None
    tenant_slug: Optional[str] = None
    overall_stage: str = "received"
    total_items: int = 0
    pending_items: int = 0
    cooking_items: int = 0
    ready_items: int = 0
    delivered_items: int = 0
    items: list[OrderItem] = []
    payment_id: Optional[str] = None


class ActivityEvent(BaseModel):
    id: str
    tenant_id: str
    occurred_at: str
    actor_type: str
    actor_id: Optional[str] = None
    actor_name: Optional[str] = None
    source: str
    action: str
    category: str
    title: str
    description: str
    table_id: Optional[str] = None
    table_number: Optional[int] = None
    order_id: Optional[str] = None
    order_item_id: Optional[str] = None
    dish_id: Optional[str] = None
    dish_name: Optional[str] = None
    quantity: Optional[int] = None
    amount: Optional[float] = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class CreateActivityEventBody(BaseModel):
    occurred_at: Optional[str] = None
    actor_type: Optional[str] = None
    actor_name: Optional[str] = None
    source: str = "management"
    action: str
    category: str
    title: str
    description: str
    table_id: Optional[str] = None
    table_number: Optional[int] = None
    order_id: Optional[str] = None
    order_item_id: Optional[str] = None
    dish_id: Optional[str] = None
    dish_name: Optional[str] = None
    quantity: Optional[int] = None
    amount: Optional[float] = None
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class UpdateQuantityBody(BaseModel):
    quantity: int


class UpdatePriceBody(BaseModel):
    price: float
    reason: Optional[str] = None


class RedsysInitiateItem(BaseModel):
    itemId: str
    portions: int = 1


class RedsysInitiateBody(BaseModel):
    orderId: str
    items: list[RedsysInitiateItem]
    method: str
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

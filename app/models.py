from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field


class Dish(BaseModel):
    id: str
    name: str
    description: str
    price: float
    is_available: bool
    category_id: str


class DishCategory(BaseModel):
    id: str
    name: str
    sort_order: int


class OrderItem(BaseModel):
    id: str
    order_id: str
    dish_name: str
    dish_price: float
    quantity: int
    notes: Optional[str] = None
    diner_name: str
    kitchen_status: str
    payment_status: str


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
    dish_name: str = Field(min_length=1, max_length=200)
    dish_price: float = Field(gt=0)
    quantity: int = Field(ge=1, le=100)
    notes: Optional[str] = Field(default=None, max_length=500)
    diner_name: Optional[str] = Field(default=None, max_length=100)


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
    items: list[NewOrderItem] = Field(min_length=1)


class AddItemsBody(BaseModel):
    items: list[NewOrderItem] = Field(min_length=1)


class CreatePaymentBody(BaseModel):
    orderId: str = Field(min_length=1)
    amount: float = Field(gt=0)
    method: str = Field(min_length=1)


class RedsysSignBody(BaseModel):
    amount: float = Field(gt=0)
    urlOk: str = Field(min_length=1)
    urlKo: str = Field(min_length=1)

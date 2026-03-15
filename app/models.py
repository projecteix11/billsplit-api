from __future__ import annotations
from typing import Optional
from pydantic import BaseModel


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
    dish_name: str
    dish_price: float
    quantity: int
    notes: Optional[str] = None
    diner_name: Optional[str] = None


class Payment(BaseModel):
    id: str
    order_id: str
    amount: float
    tip_amount: float
    total_charged: float
    payment_method: str
    status: str

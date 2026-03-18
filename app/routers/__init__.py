from fastapi import FastAPI

from app.routers import dishes, orders, order_items, payments


def register(app: FastAPI) -> None:
    app.include_router(dishes.router)
    app.include_router(orders.router)
    app.include_router(order_items.router)
    app.include_router(payments.router)

from fastapi import FastAPI

from app.routers import daily_menus, dishes, notifications, orders, order_items, payments, staff


def register(app: FastAPI) -> None:
    app.include_router(daily_menus.router)
    app.include_router(dishes.router)
    app.include_router(notifications.router)
    app.include_router(orders.router)
    app.include_router(order_items.router)
    app.include_router(payments.router)
    app.include_router(staff.router)

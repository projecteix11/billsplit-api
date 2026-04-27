from fastapi import FastAPI

from app.routers import chat, daily_menus, dishes, generate_description, notifications, orders, order_items, payments, reservations, staff, tenants


def register(app: FastAPI) -> None:
    app.include_router(chat.router)
    app.include_router(daily_menus.router)
    app.include_router(generate_description.router)
    app.include_router(dishes.router)
    app.include_router(notifications.router)
    app.include_router(orders.router)
    app.include_router(order_items.router)
    app.include_router(payments.router)
    app.include_router(reservations.router)
    app.include_router(staff.router)
    app.include_router(tenants.router)

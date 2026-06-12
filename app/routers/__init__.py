from fastapi import FastAPI

from app.routers import activity, chat, daily_menus, dishes, generate_description, guest, me, notifications, orders, order_items, payments, reservations, staff, tenants


def register(app: FastAPI) -> None:
    app.include_router(me.router, tags=["auth"])
    app.include_router(guest.router, tags=["auth"])
    app.include_router(activity.router, tags=["activity"])
    app.include_router(chat.router, tags=["chat"])
    app.include_router(daily_menus.router, tags=["daily menus"])
    app.include_router(generate_description.router, tags=["ai"])
    app.include_router(dishes.router, tags=["menu"])
    app.include_router(notifications.router, tags=["notifications"])
    app.include_router(orders.router, tags=["orders"])
    app.include_router(order_items.router, tags=["orders"])
    app.include_router(payments.router, tags=["payments"])
    app.include_router(reservations.router, tags=["reservations"])
    app.include_router(staff.router, tags=["staff"])
    app.include_router(tenants.router, tags=["tenants"])

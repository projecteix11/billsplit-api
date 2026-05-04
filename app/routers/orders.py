import traceback

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.logging import log_event, LogFactory
from app.middleware.auth import require_auth
from app.middleware.rate_limit import limiter
from app.middleware.tenant import get_current_tenant
from app.models import CreateOrderBody, AddItemsBody
from app.db import supabase
from app.services import orders as svc

router = APIRouter()


@router.post("/orders", status_code=201)
@limiter.limit("20/minute")
async def create_order(request: Request, body: CreateOrderBody, tenant_id: str = Depends(get_current_tenant)):
    if not body.tableId or not body.tableNumber or not body.items:
        return JSONResponse(
            status_code=400,
            content={"data": None, "error": "tableId, tableNumber and items[] are required"},
        )
    try:
        order = svc.create_order(body.tableId, body.tableNumber, body.items, tenant_id)
        log_event(LogFactory.order_lifecycle(
            "order_created", order.id,
            table_id=body.tableId,
            metadata={"table_number": body.tableNumber, "item_count": len(body.items)},
        ))
        return JSONResponse(status_code=201, content={"data": order.model_dump(), "error": None})
    except ValueError as e:
        return JSONResponse(status_code=400, content={"data": None, "error": str(e)})
    except Exception as e:
        log_event(LogFactory.order_lifecycle(
            "order_create_failed", "",
            table_id=body.tableId,
            metadata={"error": str(e), "traceback": traceback.format_exc()[-500:]},
        ))
        return JSONResponse(status_code=500, content={"data": None, "error": str(e)})


@router.get("/orders/{order_id}")
def get_order_by_id(order_id: str):
    try:
        order = svc.get_order_by_id(order_id)
        if order is None:
            return JSONResponse(status_code=404, content={"data": None, "error": "Order not found"})
        return {"data": order.model_dump(), "error": None}
    except Exception as e:
        return JSONResponse(status_code=500, content={"data": None, "error": str(e)})


@router.post("/orders/{order_id}/items")
@limiter.limit("20/minute")
def add_items_to_order(request: Request, order_id: str, body: AddItemsBody):
    if not body.items:
        return JSONResponse(status_code=400, content={"data": None, "error": "items[] is required"})
    try:
        svc.add_items_to_order(order_id, body.items)
        log_event(LogFactory.order_lifecycle(
            "items_added", order_id,
            metadata={"item_count": len(body.items)},
        ))
        return {"data": None, "error": None}
    except ValueError as e:
        return JSONResponse(status_code=400, content={"data": None, "error": str(e)})
    except Exception as e:
        return JSONResponse(status_code=500, content={"data": None, "error": str(e)})


@router.patch("/orders/{order_id}/close")
@limiter.limit("20/minute")
def close_order(request: Request, order_id: str, tenant_id: str = Depends(get_current_tenant)):
    try:
        svc.close_order(order_id, tenant_id)
        log_event(LogFactory.order_lifecycle("order_closed", order_id))
        return {"data": None, "error": None}
    except ValueError:
        return JSONResponse(status_code=404, content={"data": None, "error": "Order not found"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"data": None, "error": str(e)})


@router.get("/tables/{table_id}")
def get_table(table_id: str):
    try:
        rows = supabase.select("restaurant_tables", f"id=eq.{table_id}&select=id,number,status,active_order_id")
        if not rows:
            return JSONResponse(status_code=404, content={"data": None, "error": "Table not found"})
        return {"data": rows[0], "error": None}
    except Exception as e:
        return JSONResponse(status_code=500, content={"data": None, "error": str(e)})


@router.get("/tables/{table_id}/open-order")
def get_open_order_for_table(table_id: str):
    try:
        order = svc.get_open_order_for_table(table_id)
        return {"data": order.model_dump() if order else None, "error": None}
    except Exception as e:
        return JSONResponse(status_code=500, content={"data": None, "error": str(e)})


@router.get("/orders")
async def list_orders(status: str = "open", kitchen_only: bool = False, _user_id: str = Depends(require_auth), tenant_id: str = Depends(get_current_tenant)):
    if status not in ("open", "closed"):
        return JSONResponse(
            status_code=400,
            content={"data": None, "error": "status must be open or closed"},
        )
    try:
        orders = svc.fetch_orders(tenant_id, status, kitchen_only=kitchen_only)
        return {"data": [o.model_dump() for o in orders], "error": None}
    except Exception as e:
        return JSONResponse(status_code=500, content={"data": None, "error": str(e)})

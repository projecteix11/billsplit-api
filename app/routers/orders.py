from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.middleware.auth import require_auth
from app.middleware.error_handling import safe_error_response
from app.middleware.rate_limit import limiter
from app.models import CreateOrderBody, AddItemsBody
from app.services import orders as svc

router = APIRouter()


@router.post("/api/orders", status_code=201)
@limiter.limit("20/minute")
def create_order(request: Request, body: CreateOrderBody):
    try:
        order = svc.create_order(body.tableId, body.tableNumber, body.items)
        return JSONResponse(status_code=201, content={"data": order.model_dump(), "error": None})
    except Exception as e:
        return JSONResponse(status_code=500, content={"data": None, "error": safe_error_response(e, "create_order")})


@router.get("/api/orders/{order_id}")
def get_order_by_id(order_id: str):
    try:
        order = svc.get_order_by_id(order_id)
        if order is None:
            return JSONResponse(status_code=404, content={"data": None, "error": "Order not found"})
        return {"data": order.model_dump(), "error": None}
    except Exception as e:
        return JSONResponse(status_code=500, content={"data": None, "error": safe_error_response(e, "get_order_by_id")})


@router.post("/api/orders/{order_id}/items")
@limiter.limit("20/minute")
def add_items_to_order(request: Request, order_id: str, body: AddItemsBody, _user_id: str = Depends(require_auth)):
    try:
        svc.add_items_to_order(order_id, body.items)
        return {"data": None, "error": None}
    except Exception as e:
        return JSONResponse(status_code=500, content={"data": None, "error": safe_error_response(e, "add_items_to_order")})


@router.patch("/api/orders/{order_id}/close")
@limiter.limit("20/minute")
def close_order(request: Request, order_id: str, _user_id: str = Depends(require_auth)):
    try:
        svc.close_order(order_id)
        return {"data": None, "error": None}
    except Exception as e:
        return JSONResponse(status_code=500, content={"data": None, "error": safe_error_response(e, "close_order")})


@router.get("/api/tables/{table_id}/open-order")
def get_open_order_for_table(table_id: str):
    try:
        order = svc.get_open_order_for_table(table_id)
        if order is None:
            return JSONResponse(
                status_code=404,
                content={"data": None, "error": "No open order for this table"},
            )
        return {"data": order.model_dump(), "error": None}
    except Exception as e:
        return JSONResponse(status_code=500, content={"data": None, "error": safe_error_response(e, "get_open_order_for_table")})


@router.get("/api/orders")
def list_orders(status: str = "open", _user_id: str = Depends(require_auth)):
    if status not in ("open", "closed"):
        return JSONResponse(
            status_code=400,
            content={"data": None, "error": "status must be open or closed"},
        )
    try:
        orders = svc.fetch_orders(status)
        return {"data": [o.model_dump() for o in orders], "error": None}
    except Exception as e:
        return JSONResponse(status_code=500, content={"data": None, "error": safe_error_response(e, "list_orders")})

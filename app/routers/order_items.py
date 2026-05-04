from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.logging import log_event, LogFactory
from app.middleware.auth import require_auth
from app.middleware.tenant import require_feature, get_current_tenant
from app.middleware.rate_limit import limiter
from app.models import UpdateQuantityBody, UpdatePriceBody
from app.services import orders as svc

router = APIRouter()

VALID_KITCHEN_STATUSES = {"pending", "cooking", "ready", "delivered", "cancelled"}
VALID_PAYMENT_STATUSES = {"unassigned", "assigned", "paid"}


class KitchenStatusBody(BaseModel):
    status: str


class PaymentStatusBody(BaseModel):
    itemIds: list[str]
    status: str


@router.patch("/order-items/{item_id}/kitchen-status")
@limiter.limit("20/minute")
def update_kitchen_status(request: Request, item_id: str, body: KitchenStatusBody, _user_id: str = Depends(require_auth), _tenant_id: str = Depends(require_feature("kitchen"))):
    if body.status not in VALID_KITCHEN_STATUSES:
        return JSONResponse(
            status_code=400,
            content={"data": None, "error": "status must be one of: pending, cooking, ready, delivered, cancelled"},
        )
    try:
        svc.update_item_kitchen_status(item_id, body.status)
        log_event(LogFactory.order_lifecycle(
            "kitchen_status_changed", "",
            metadata={"item_id": item_id, "new_status": body.status},
        ))
        return {"data": None, "error": None}
    except Exception as e:
        return JSONResponse(status_code=500, content={"data": None, "error": str(e)})


@router.patch("/order-items/payment-status")
@limiter.limit("20/minute")
def update_payment_status(request: Request, body: PaymentStatusBody, tenant_id: str = Depends(require_feature("payments"))):
    if not body.itemIds:
        return JSONResponse(status_code=400, content={"data": None, "error": "itemIds[] is required"})
    if body.status not in VALID_PAYMENT_STATUSES:
        return JSONResponse(
            status_code=400,
            content={"data": None, "error": "status must be one of: unassigned, assigned, paid"},
        )
    try:
        svc.update_items_payment_status(body.itemIds, body.status, tenant_id)
        if body.status == "paid":
            svc.auto_close_orders_for_items(body.itemIds)
        log_event(LogFactory.order_lifecycle(
            "payment_status_changed", "",
            metadata={"item_ids": body.itemIds, "new_status": body.status},
        ))
        return {"data": None, "error": None}
    except ValueError:
        return JSONResponse(status_code=404, content={"data": None, "error": "Order item not found"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"data": None, "error": str(e)})


@router.delete("/order-items/{item_id}")
@limiter.limit("20/minute")
def delete_order_item(request: Request, item_id: str, _user_id: str = Depends(require_auth), tenant_id: str = Depends(get_current_tenant)):
    try:
        svc.delete_order_item(item_id, tenant_id)
        log_event(LogFactory.order_lifecycle(
            "order_item_deleted", "",
            metadata={"item_id": item_id},
        ))
        return {"data": None, "error": None}
    except ValueError:
        return JSONResponse(status_code=404, content={"data": None, "error": "Order item not found"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"data": None, "error": str(e)})


@router.patch("/order-items/{item_id}/quantity")
@limiter.limit("20/minute")
def update_item_quantity(request: Request, item_id: str, body: UpdateQuantityBody, _user_id: str = Depends(require_auth), tenant_id: str = Depends(get_current_tenant)):
    try:
        svc.update_order_item_quantity(item_id, body.quantity, tenant_id)
        log_event(LogFactory.order_lifecycle(
            "order_item_quantity_updated", "",
            metadata={"item_id": item_id, "new_quantity": body.quantity},
        ))
        return {"data": None, "error": None}
    except ValueError:
        return JSONResponse(status_code=404, content={"data": None, "error": "Order item not found"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"data": None, "error": str(e)})


@router.patch("/order-items/{item_id}/price")
@limiter.limit("20/minute")
def update_item_price(request: Request, item_id: str, body: UpdatePriceBody, _user_id: str = Depends(require_auth), tenant_id: str = Depends(get_current_tenant)):
    try:
        svc.update_order_item_price(item_id, body.price, tenant_id, reason=body.reason)
        log_event(LogFactory.order_lifecycle(
            "order_item_price_updated", "",
            metadata={"item_id": item_id, "new_price": body.price, "reason": body.reason},
        ))
        return {"data": None, "error": None}
    except ValueError:
        return JSONResponse(status_code=404, content={"data": None, "error": "Order item not found"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"data": None, "error": str(e)})

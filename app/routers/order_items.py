from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.logging import log_event, LogFactory
from app.middleware.auth import require_auth
from app.middleware.rate_limit import limiter
from app.services import orders as svc

router = APIRouter()

VALID_KITCHEN_STATUSES = {"pending", "cooking", "ready", "delivered"}
VALID_PAYMENT_STATUSES = {"unassigned", "assigned", "paid"}


class KitchenStatusBody(BaseModel):
    status: str


class PaymentStatusBody(BaseModel):
    itemIds: list[str]
    status: str


@router.patch("/api/order-items/{item_id}/kitchen-status")
@limiter.limit("20/minute")
def update_kitchen_status(request: Request, item_id: str, body: KitchenStatusBody, _user_id: str = Depends(require_auth)):
    if body.status not in VALID_KITCHEN_STATUSES:
        return JSONResponse(
            status_code=400,
            content={"data": None, "error": "status must be one of: pending, cooking, ready, delivered"},
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


@router.patch("/api/order-items/payment-status")
@limiter.limit("20/minute")
def update_payment_status(request: Request, body: PaymentStatusBody):
    if not body.itemIds:
        return JSONResponse(status_code=400, content={"data": None, "error": "itemIds[] is required"})
    if body.status not in VALID_PAYMENT_STATUSES:
        return JSONResponse(
            status_code=400,
            content={"data": None, "error": "status must be one of: unassigned, assigned, paid"},
        )
    try:
        svc.update_items_payment_status(body.itemIds, body.status)
        log_event(LogFactory.order_lifecycle(
            "payment_status_changed", "",
            metadata={"item_ids": body.itemIds, "new_status": body.status},
        ))
        return {"data": None, "error": None}
    except Exception as e:
        return JSONResponse(status_code=500, content={"data": None, "error": str(e)})

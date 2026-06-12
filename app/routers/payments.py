import traceback

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.middleware.auth import require_auth, require_customer_principal
from app.middleware.rate_limit import limiter
from app.middleware.tenant import require_feature
from app.models import CreatePaymentBody, RedsysInitiateBody
from app.logging import log_event, LogFactory
from app.services import activity as activity_svc
from app.services import orders as order_svc
from app.services import payments as svc

router = APIRouter()


@router.post("/payments", status_code=201)
@limiter.limit("20/minute")
def create_payment(request: Request, body: CreatePaymentBody, _user_id: str = Depends(require_auth), _tenant_id: str = Depends(require_feature("payments"))):
    if not body.orderId or not body.amount or not body.method:
        return JSONResponse(
            status_code=400,
            content={"data": None, "error": "orderId, amount and method are required"},
        )
    try:
        payment = svc.create_payment(body.orderId, body.amount, body.method)
        log_event(LogFactory.payment_event(
            "payment_created", body.orderId, body.amount, body.method,
        ))
        order = order_svc.get_order_by_id(body.orderId)
        activity_svc.record_payment_created(
            request=request,
            tenant_id=_tenant_id,
            order=order.model_dump() if order else None,
            order_id=body.orderId,
            amount=body.amount,
            method=body.method,
        )
        return JSONResponse(status_code=201, content={"data": payment.model_dump(), "error": None})
    except Exception as e:
        log_event(LogFactory.payment_event(
            "payment_failed", body.orderId, body.amount, body.method,
            error=str(e),
        ))
        return JSONResponse(status_code=500, content={"data": None, "error": str(e)})


@router.get("/payments/redsys/{order_number}")
def get_redsys_payment(order_number: str):
    """Public lookup of a payment by its Redsys order number. After the S2S
    callback confirms, the diner frontend calls this to get the payment id (and
    status) so it can offer a Verifactu invoice — the client no longer creates
    the payment, so it can't learn the id any other way. The order number is an
    opaque, server-generated 12-digit handle the client already holds; only
    minimal, non-PII payment fields are returned."""
    try:
        payment = svc.get_payment_by_redsys_order(order_number)
        if payment is None:
            return JSONResponse(status_code=404, content={"data": None, "error": "Payment not found"})
        return {"data": payment.model_dump(), "error": None}
    except Exception as e:
        return JSONResponse(status_code=500, content={"data": None, "error": str(e)})


@router.post("/payments/redsys-initiate")
@limiter.limit("20/minute")
def redsys_initiate(request: Request, body: RedsysInitiateBody, _principal: None = Depends(require_customer_principal)):
    """Server-authoritative Redsys initiation. The client sends orderId + the
    items (+ portions) it wants to pay — NEVER an amount. The server computes the
    amount from the DB, persists a pending payment keyed to the Redsys order
    number, and returns the signed request. Confirmation happens only via the
    Redsys S2S callback (the sole writer of payment_status='paid')."""
    if not body.orderId or not body.items or not body.method:
        return JSONResponse(
            status_code=400,
            content={"data": None, "error": "orderId, items and method are required"},
        )
    try:
        result = svc.initiate_redsys(body.orderId, body.items, body.method, body.urlOk, body.urlKo)
        log_event(LogFactory.payment_event(
            "redsys_initiated", body.orderId, 0, body.method,
        ))
        return result
    except ValueError as e:
        return JSONResponse(status_code=400, content={"data": None, "error": str(e)})
    except Exception as e:
        log_event(LogFactory.payment_event(
            "redsys_initiate_failed", body.orderId, 0, body.method,
            error=str(e),
        ))
        return JSONResponse(status_code=500, content={"data": None, "error": "Internal server error"})

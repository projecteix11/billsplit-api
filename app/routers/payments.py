import traceback

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import JSONResponse

from app.middleware.auth import require_auth, require_customer_principal
from app.middleware.rate_limit import limiter
from app.middleware.tenant import require_feature
from app.models import CreatePaymentBody, RedsysInitiateBody
from app.logging import log_event, LogFactory
from app.services import activity as activity_svc
from app.services import orders as order_svc
from app.services import payments as svc
from app.http_errors import internal_error

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
        payment = svc.create_payment(body.orderId, body.amount, body.method, body.coveredItems)
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
        return internal_error(e)


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
        return internal_error(e)


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
        from urllib.parse import quote
        base_url = str(request.base_url).rstrip('/')
        # Wrap URL OK and KO through the backend to avoid Vercel static route POST 405 error
        wrapped_url_ok = f"{base_url}/payments/redsys-return-ok?redirect_url={quote(body.urlOk)}"
        wrapped_url_ko = f"{base_url}/payments/redsys-return-ko?redirect_url={quote(body.urlKo)}"
        result = svc.initiate_redsys(body.orderId, body.items, body.method, wrapped_url_ok, wrapped_url_ko)
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


@router.post("/payments/redsys-return-ok")
@router.get("/payments/redsys-return-ok")
def redsys_return_ok(redirect_url: str):
    """Handle Redsys success return. Redirects the browser using GET 303 to the frontend."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(redirect_url, status_code=303)


@router.post("/payments/redsys-return-ko")
@router.get("/payments/redsys-return-ko")
def redsys_return_ko(redirect_url: str):
    """Handle Redsys cancellation/error return. Redirects the browser using GET 303 to the frontend."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(redirect_url, status_code=303)


@router.post("/payments/mock-confirm/{order_number}")
def mock_confirm_payment(order_number: str):
    import os
    if os.getenv("APP_ENV") != "local":
        return JSONResponse(status_code=403, content={"error": "Only allowed in local development"})
    try:
        payment = svc.get_payment_by_redsys_order(order_number)
        if not payment:
            return JSONResponse(status_code=404, content={"error": "Payment not found"})
        amount_cents = int(round(payment.amount * 100))
        svc.confirm_redsys_payment(order_number, amount_cents)
        return {"data": "confirmed", "error": None}
    except Exception as e:
        return internal_error(e)


@router.post("/payments/redsys-notify")
async def redsys_notify(
    request: Request,
    Ds_SignatureVersion: str = Form(default=""),
    Ds_MerchantParameters: str = Form(default=""),
    Ds_Signature: str = Form(default=""),
):
    """Redsys server-to-server (S2S) notification endpoint.

    Redsys POSTs here (application/x-www-form-urlencoded) immediately after a
    payment is authorised on their end.  We verify the HMAC_SHA256_V1 signature,
    then confirm the payment and update order items.

    Redsys expects an empty 200 OK response on success and considers any other
    status a delivery failure (and retries).  We must NOT return a redirect here.

    This endpoint is PUBLIC (no auth header from Redsys) but is protected by
    the HMAC signature — forging a notification would require knowing the secret.
    """
    try:
        if not Ds_MerchantParameters or not Ds_Signature:
            # Try reading from raw body in case the form parser missed it
            body_bytes = await request.body()
            body_text = body_bytes.decode("utf-8", errors="replace")
            log_event(LogFactory.payment_event(
                "redsys_notify_missing_params", "", 0, "",
                error=f"Missing form fields. Body: {body_text[:200]}",
            ))
            return JSONResponse(status_code=400, content={"error": "Missing Ds_MerchantParameters or Ds_Signature"})

        # Verify signature and decode params
        params = svc.verify_redsys_signature(Ds_MerchantParameters, Ds_Signature)

        redsys_order_number = params.get("Ds_Order", "")
        amount_cents = int(params.get("Ds_Amount", 0))

        log_event(LogFactory.payment_event(
            "redsys_notify_received", redsys_order_number, amount_cents / 100, "",
        ))

        svc.confirm_redsys_payment(redsys_order_number, amount_cents)

        log_event(LogFactory.payment_event(
            "redsys_notify_confirmed", redsys_order_number, amount_cents / 100, "",
        ))

        # Redsys requires an empty 200 OK
        return JSONResponse(status_code=200, content={})

    except ValueError as e:
        log_event(LogFactory.payment_event(
            "redsys_notify_rejected", "", 0, "",
            error=str(e),
        ))
        # Return 200 to Redsys even on signature failure to avoid infinite retries;
        # we log the rejection and it's auditable.
        return JSONResponse(status_code=200, content={"error": str(e)})

    except Exception as e:
        log_event(LogFactory.payment_event(
            "redsys_notify_error", "", 0, "",
            error=str(e),
        ))
        # Return 200 so Redsys doesn't keep retrying on server errors
        return JSONResponse(status_code=200, content={"error": "internal error"})

from fastapi import APIRouter, Request
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.middleware.rate_limit import limiter
from app.models import CreatePaymentBody, RedsysSignBody
from app.services import payments as svc

router = APIRouter()


@router.post("/api/payments", status_code=201)
@limiter.limit("20/minute")
def create_payment(request: Request, body: CreatePaymentBody):
@limiter.limit("20/minute")
def create_payment(request: Request, body: CreatePaymentBody):
    if not body.orderId or not body.amount or not body.method:
        return JSONResponse(
            status_code=400,
            content={"data": None, "error": "orderId, amount and method are required"},
        )
    try:
        payment = svc.create_payment(body.orderId, body.amount, body.method)
        return JSONResponse(status_code=201, content={"data": payment.model_dump(), "error": None})
    except Exception as e:
        return JSONResponse(status_code=500, content={"data": None, "error": str(e)})


@router.post("/api/payments/redsys-sign")
@limiter.limit("20/minute")
def redsys_sign(request: Request, body: RedsysSignBody):
@limiter.limit("20/minute")
def redsys_sign(request: Request, body: RedsysSignBody):
    if not body.amount or not body.urlOk or not body.urlKo:
        return JSONResponse(
            status_code=400,
            content={"data": None, "error": "amount, urlOk and urlKo are required"},
        )
    try:
        result = svc.sign_redsys(body.amount, body.urlOk, body.urlKo)
        return result.dict()
    except Exception as e:
        return JSONResponse(status_code=500, content={"data": None, "error": str(e)})

import traceback

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.logging import log_event, LogFactory
from app.services import payments as svc

router = APIRouter()


class CreatePaymentBody(BaseModel):
    orderId: str
    amount: float
    method: str


class RedsysSignBody(BaseModel):
    amount: float
    urlOk: str
    urlKo: str


@router.post("/api/payments", status_code=201)
def create_payment(body: CreatePaymentBody):
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
        return JSONResponse(status_code=201, content={"data": payment.model_dump(), "error": None})
    except Exception as e:
        log_event(LogFactory.payment_event(
            "payment_failed", body.orderId, body.amount, body.method,
            error=str(e),
        ))
        return JSONResponse(status_code=500, content={"data": None, "error": str(e)})


@router.post("/api/payments/redsys-sign")
def redsys_sign(body: RedsysSignBody):
    if not body.amount or not body.urlOk or not body.urlKo:
        return JSONResponse(
            status_code=400,
            content={"data": None, "error": "amount, urlOk and urlKo are required"},
        )
    try:
        result = svc.sign_redsys(body.amount, body.urlOk, body.urlKo)
        log_event(LogFactory.payment_event(
            "redsys_sign_ok", "", body.amount, "redsys",
        ))
        return result.dict()
    except Exception as e:
        log_event(LogFactory.payment_event(
            "redsys_sign_failed", "", body.amount, "redsys",
            error=str(e),
        ))
        return JSONResponse(status_code=500, content={"data": None, "error": str(e)})

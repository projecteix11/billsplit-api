from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.middleware.auth import require_auth
from app.middleware.error_handling import safe_error_response
from app.middleware.rate_limit import limiter
from app.models import CreatePaymentBody, RedsysSignBody
from app.services import payments as svc

router = APIRouter()


@router.post("/api/payments", status_code=201)
@limiter.limit("20/minute")
def create_payment(request: Request, body: CreatePaymentBody, _user_id: str = Depends(require_auth)):
    try:
        payment = svc.create_payment(body.orderId, body.amount, body.method)
        return JSONResponse(status_code=201, content={"data": payment.model_dump(), "error": None})
    except Exception as e:
        return JSONResponse(status_code=500, content={"data": None, "error": safe_error_response(e, "create_payment")})


@router.post("/api/payments/redsys-sign")
@limiter.limit("20/minute")
def redsys_sign(request: Request, body: RedsysSignBody, _user_id: str = Depends(require_auth)):
    try:
        result = svc.sign_redsys(body.amount, body.urlOk, body.urlKo)
        return result.dict()
    except Exception as e:
        return JSONResponse(status_code=500, content={"data": None, "error": safe_error_response(e, "redsys_sign")})

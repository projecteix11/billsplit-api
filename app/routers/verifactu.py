from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.middleware.auth import require_customer_principal
from app.middleware.rate_limit import limiter
from app.middleware.tenant import get_current_tenant
from app.services import verifactu as svc

router = APIRouter()


class Destinatario(BaseModel):
    nombre: str
    nif: str


class CreateInvoiceBody(BaseModel):
    orderId: str
    paymentId: str
    tipoFactura: str = "F2"
    destinatario: Destinatario | None = None


@router.get("/verifactu/config")
@limiter.limit("60/minute")
def get_config(request: Request, tenant_id: str = Depends(get_current_tenant)):
    """Public-safe Verifactu config for the current tenant (derived server-side).
    Replaces the diner's old direct anon read of `verifactu_config`, which the
    Phase 0.4 RLS lockdown revoked. Returns null data when there is no config."""
    try:
        return JSONResponse(status_code=200, content={"data": svc.get_config(tenant_id), "error": None})
    except Exception as e:
        return JSONResponse(status_code=500, content={"data": None, "error": str(e)})


@router.post("/verifactu/invoice")
@limiter.limit("20/minute")
def create_invoice(
    request: Request,
    body: CreateInvoiceBody,
    tenant_id: str = Depends(get_current_tenant),
    _principal: None = Depends(require_customer_principal),
):
    """Create a Verifactu invoice for a paid order. Tenant is derived from the
    request (guest token / staff JWT), never from a client-supplied id."""
    try:
        result = svc.create_invoice(
            tenant_id,
            body.orderId,
            body.paymentId,
            body.tipoFactura,
            body.destinatario.nombre if body.destinatario else None,
            body.destinatario.nif if body.destinatario else None,
        )
        return JSONResponse(status_code=200, content={"data": result, "error": None})
    except Exception as e:
        return JSONResponse(status_code=500, content={"data": None, "error": str(e)})


@router.post("/verifactu/invoice/{invoice_id}/pdf")
@limiter.limit("30/minute")
def generate_pdf(
    request: Request,
    invoice_id: str,
    tenant_id: str = Depends(get_current_tenant),
    _principal: None = Depends(require_customer_principal),
):
    """Render + return the stored PDF url for an invoice."""
    try:
        result = svc.generate_pdf(tenant_id, invoice_id)
        return JSONResponse(status_code=200, content={"data": result, "error": None})
    except Exception as e:
        return JSONResponse(status_code=500, content={"data": None, "error": str(e)})

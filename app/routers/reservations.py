from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.middleware.auth import require_auth
from app.middleware.rate_limit import limiter
from app.middleware.tenant import require_feature
from app.db import supabase

router = APIRouter()


class UpdateReservationBody(BaseModel):
    status: str | None = None
    notes: str | None = None


class CreateReservationBody(BaseModel):
    name: str
    email: str
    phone: str | None = None
    date: str          # ISO date: YYYY-MM-DD
    time: str          # HH:MM
    party_size: int
    notes: str | None = None


@router.post("/reservations", status_code=201)
@limiter.limit("10/minute")
async def create_reservation(
    request: Request,
    body: CreateReservationBody,
    tenant_id: str = Depends(require_feature("reservations")),
):
    if not 1 <= body.party_size <= 20:
        return JSONResponse(status_code=422, content={"data": None, "error": "party_size must be between 1 and 20"})
    try:
        rows = supabase.insert("reservations", {
            "tenant_id": tenant_id,
            "name": body.name,
            "email": body.email,
            "phone": body.phone,
            "date": body.date,
            "time": body.time,
            "party_size": body.party_size,
            "notes": body.notes,
            "status": "pending",
        })
        return JSONResponse(status_code=201, content={"data": rows[0] if rows else None, "error": None})
    except Exception as e:
        return JSONResponse(status_code=500, content={"data": None, "error": str(e)})


@router.get("/reservations")
async def list_reservations(
    _user_id: str = Depends(require_auth),
    tenant_id: str = Depends(require_feature("reservations")),
):
    try:
        rows = supabase.select("reservations", f"tenant_id=eq.{tenant_id}&order=date.asc,time.asc")
        return {"data": rows, "error": None}
    except Exception as e:
        return JSONResponse(status_code=500, content={"data": None, "error": str(e)})


@router.patch("/reservations/{reservation_id}")
@limiter.limit("20/minute")
async def update_reservation(
    request: Request,
    reservation_id: str,
    body: UpdateReservationBody,
    _user_id: str = Depends(require_auth),
):
    patch = body.model_dump(exclude_none=True)
    if not patch:
        return JSONResponse(status_code=422, content={"data": None, "error": "No valid fields to update"})
    try:
        supabase.update("reservations", f"id=eq.{reservation_id}", patch)
        return {"data": None, "error": None}
    except Exception as e:
        return JSONResponse(status_code=500, content={"data": None, "error": str(e)})

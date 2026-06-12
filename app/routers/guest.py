from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.middleware.rate_limit import limiter
from app.services import guest_session as svc

router = APIRouter()


class GuestSessionBody(BaseModel):
    tableId: str


@router.post("/guest-session", status_code=201)
@limiter.limit("30/minute")
def open_guest_session(request: Request, body: GuestSessionBody):
    """Issue a short-lived guest session token for a scanned table (XM-6).

    The diner's app calls this at QR scan. The tenant is derived from the table
    server-side, so the returned token carries a trusted tenant/table claim the
    API can use instead of the spoofable X-Tenant-Slug header. Public by design
    (the diner has no credential yet — this is how they get one)."""
    if not body.tableId:
        return JSONResponse(status_code=400, content={"data": None, "error": "tableId is required"})
    try:
        session = svc.open_guest_session(body.tableId)
        if session is None:
            return JSONResponse(status_code=404, content={"data": None, "error": "Table not found"})
        return JSONResponse(status_code=201, content={"data": session, "error": None})
    except Exception as e:
        return JSONResponse(status_code=500, content={"data": None, "error": str(e)})

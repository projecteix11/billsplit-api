from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.db import supabase
from app.middleware.auth import require_auth

router = APIRouter()


@router.get("/tenants")
def list_tenants(request: Request, user_id: str = Depends(require_auth)):
    role = getattr(request.state, "role", None)
    if role != "developer":
        return JSONResponse(status_code=403, content={"data": None, "error": "Forbidden"})
    rows = supabase.select("tenants", "select=id,name,slug,is_active&order=name.asc")
    return {"data": rows, "error": None}


@router.get("/tenants/by-slug/{slug}")
def get_tenant_by_slug(slug: str):
    try:
        rows = supabase.select(
            "tenants",
            f"select=id,name,slug,features,branding&slug=eq.{slug}&is_active=eq.true&limit=1",
        )
        if not rows:
            return JSONResponse(status_code=404, content={"data": None, "error": "Tenant not found"})
        return {"data": rows[0], "error": None}
    except Exception as e:
        return JSONResponse(status_code=500, content={"data": None, "error": str(e)})

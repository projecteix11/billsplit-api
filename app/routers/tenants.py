from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.db.supabase import get_client
from app.middleware.auth import require_auth

router = APIRouter()


class TenantListedUpdate(BaseModel):
    is_listed: bool


@router.get("/tenants")
def list_tenants(request: Request, user_id: str = Depends(require_auth)):
    role = getattr(request.state, "role", None)
    if role != "developer":
        return JSONResponse(status_code=403, content={"data": None, "error": "Forbidden"})
    rows = get_client().table("tenants").select("id,name,slug,is_active,is_listed").order("name").execute().data or []
    return {"data": rows, "error": None}


@router.patch("/tenants/{tenant_id}/listed")
def set_tenant_listed(
    tenant_id: str,
    payload: TenantListedUpdate,
    request: Request,
    user_id: str = Depends(require_auth),
):
    """Toggle whether a tenant appears in the public directory (developer only)."""
    role = getattr(request.state, "role", None)
    if role != "developer":
        return JSONResponse(status_code=403, content={"data": None, "error": "Forbidden"})
    try:
        rows = (
            get_client()
            .table("tenants")
            .update({"is_listed": payload.is_listed})
            .eq("id", tenant_id)
            .execute()
            .data or []
        )
        if not rows:
            return JSONResponse(status_code=404, content={"data": None, "error": "Tenant not found"})
        return {"data": rows[0], "error": None}
    except Exception as e:
        return JSONResponse(status_code=500, content={"data": None, "error": str(e)})


@router.get("/tenants/public")
def list_public_tenants():
    """Public restaurant directory for the marketing site (gobbly.app).

    Returns only active tenants that opted in (is_listed = true). No auth.
    """
    try:
        rows = (
            get_client()
            .table("tenants")
            .select("id,name,slug,city,logo_url,branding")
            .eq("is_active", True)
            .eq("is_listed", True)
            .order("name")
            .execute()
            .data or []
        )
        return {"data": rows, "error": None}
    except Exception as e:
        return JSONResponse(status_code=500, content={"data": None, "error": str(e)})


@router.get("/tenants/by-slug/{slug}")
def get_tenant_by_slug(slug: str):
    try:
        rows = (
            get_client()
            .table("tenants")
            .select("id,name,slug,features,branding")
            .eq("slug", slug)
            .eq("is_active", True)
            .limit(1)
            .execute()
            .data or []
        )
        if not rows:
            return JSONResponse(status_code=404, content={"data": None, "error": "Tenant not found"})
        return {"data": rows[0], "error": None}
    except Exception as e:
        return JSONResponse(status_code=500, content={"data": None, "error": str(e)})

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.db import supabase
from app.middleware.auth import require_auth

router = APIRouter()


@router.get("/me")
def get_me(request: Request, user_id: str = Depends(require_auth)):
    tenant_id = getattr(request.state, "tenant_id", None)
    if not tenant_id:
        return JSONResponse(status_code=400, content={"data": None, "error": "No tenant associated with this user"})

    tenant_rows = supabase.select(
        "tenants",
        f"select=id,slug,plan,features,is_active&id=eq.{tenant_id}&limit=1",
    )
    if not tenant_rows:
        return JSONResponse(status_code=404, content={"data": None, "error": "Tenant not found"})

    role_rows = supabase.select(
        "user_roles",
        f"select=role&user_id=eq.{user_id}&tenant_id=eq.{tenant_id}&limit=1",
    )
    role = role_rows[0]["role"] if role_rows else None

    tenant = tenant_rows[0]
    return {
        "data": {
            "user_id": user_id,
            "tenant": {
                "id": tenant["id"],
                "slug": tenant["slug"],
                "plan": tenant["plan"],
                "features": tenant["features"],
                "is_active": tenant["is_active"],
            },
            "role": role,
        },
        "error": None,
    }

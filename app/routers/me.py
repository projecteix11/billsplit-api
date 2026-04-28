from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.db import supabase
from app.middleware.auth import require_auth

router = APIRouter()


@router.get("/me")
def get_me(request: Request, user_id: str = Depends(require_auth)):
    role = getattr(request.state, "role", None)
    tenant_id = getattr(request.state, "tenant_id", None)

    if role == "developer":
        return {
            "data": {
                "user_id": user_id,
                "tenant": None,
                "role": role,
                "is_platform_user": True,
            },
            "error": None,
        }

    if not tenant_id:
        return JSONResponse(status_code=400, content={"data": None, "error": "No tenant associated with this user"})

    tenant_rows = supabase.select(
        "tenants",
        f"select=id,slug,plan,features,is_active,trial_ends_at&id=eq.{tenant_id}&limit=1",
    )
    if not tenant_rows:
        return JSONResponse(status_code=404, content={"data": None, "error": "Tenant not found"})

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
                "trial_ends_at": tenant["trial_ends_at"],
            },
            "role": role,
            "is_platform_user": False,
        },
        "error": None,
    }

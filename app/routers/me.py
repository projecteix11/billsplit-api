from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.db.supabase import get_client
from app.middleware.auth import require_auth

router = APIRouter()


@router.get("/me")
def get_me(request: Request, user_id: str = Depends(require_auth)):
    role = getattr(request.state, "role", None)
    tenant_id = getattr(request.state, "tenant_id", None)

    user_rows = get_client().table("users").select("avatar_url").eq("id", user_id).limit(1).execute().data or []
    avatar_url = user_rows[0]["avatar_url"] if user_rows else None

    if role == "developer":
        return {
            "data": {
                "user_id": user_id,
                "tenant": None,
                "role": role,
                "is_platform_user": True,
                "avatar_url": avatar_url,
            },
            "error": None,
        }

    if not tenant_id:
        return JSONResponse(status_code=400, content={"data": None, "error": "No tenant associated with this user"})

    tenant_rows = (
        get_client()
        .table("tenants")
        .select("id,slug,plan,features,is_active,trial_ends_at,max_users,branding,surcharges")
        .eq("id", tenant_id)
        .limit(1)
        .execute()
        .data or []
    )
    if not tenant_rows:
        return JSONResponse(status_code=404, content={"data": None, "error": "Tenant not found"})

    tenant = tenant_rows[0]
    branding = tenant.get("branding") or {}
    return {
        "data": {
            "user_id": user_id,
            "tenant": {
                "id": tenant["id"],
                "slug": tenant["slug"],
                "plan": tenant["plan"],
                "features": tenant["features"],
                "surcharges": tenant.get("surcharges") or {},
                "is_active": tenant["is_active"],
                "trial_ends_at": tenant["trial_ends_at"],
                "max_users": tenant["max_users"],
                "paypal_user": branding.get("paypalUser"),
            },
            "role": role,
            "is_platform_user": False,
            "avatar_url": avatar_url,
        },
        "error": None,
    }

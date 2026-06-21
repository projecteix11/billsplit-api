import os

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from app.db.supabase import is_platform_admin, verify_token_full
from app.services.notifications import broadcast_notification

router = APIRouter(prefix="/notifications", tags=["notifications"])

# Server-side only. Genuine service-to-service callers may still authenticate
# with this; it is NOT shipped to any browser bundle.
_INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "")


class NotificationRequest(BaseModel):
    title: str
    description: str | None = None
    notification_type: str = "system_alert"
    params: dict | None = None


def _authorize(authorization: str | None, x_api_key: str | None) -> None:
    """Authorize a broadcast caller. Two accepted principals:

    - a **platform-admin Supabase JWT** (the adminPanel super-admin), verified
      against the `platform_admins` table, or
    - the server-side **internal API key** (genuine service-to-service callers).

    Previously the only gate was a static `X-Api-Key` that the adminPanel shipped
    in its public JS bundle as `VITE_NOTIFICATIONS_KEY` (XC-3 / api O12). Anyone
    could extract it and, because `X-Tenant-Id` is caller-supplied, broadcast to
    *any* tenant. The key is no longer sent from the browser; the adminPanel now
    authenticates as the logged-in platform admin, and broadcasting to any tenant
    is legitimate for that role.
    """
    if authorization and authorization.startswith("Bearer "):
        try:
            user_id, _, _ = verify_token_full(authorization[7:])
        except Exception:
            raise HTTPException(status_code=401, detail="Invalid or expired token")
        if is_platform_admin(user_id):
            return
        raise HTTPException(status_code=403, detail="Platform admin privileges required")

    if x_api_key and _INTERNAL_API_KEY and x_api_key == _INTERNAL_API_KEY:
        return

    raise HTTPException(status_code=403, detail="Authentication required")


@router.post("/broadcast")
def send_broadcast(
    body: NotificationRequest,
    x_tenant_id: str = Header(),
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None),
):
    _authorize(authorization, x_api_key)
    broadcast_notification(
        tenant_id=x_tenant_id,
        title=body.title,
        description=body.description,
        notification_type=body.notification_type,
        params=body.params,
    )
    return {"data": {"status": "sent"}}

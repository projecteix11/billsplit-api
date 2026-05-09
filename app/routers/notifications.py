import os

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from app.services.notifications import broadcast_notification

router = APIRouter(prefix="/notifications", tags=["notifications"])

_INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "")


class NotificationRequest(BaseModel):
    title: str
    description: str | None = None
    notification_type: str = "system_alert"
    params: dict | None = None


@router.post("/broadcast")
def send_broadcast(
    body: NotificationRequest,
    x_api_key: str = Header(),
    x_tenant_id: str = Header(),
):
    if not _INTERNAL_API_KEY or x_api_key != _INTERNAL_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API key")
    broadcast_notification(
        tenant_id=x_tenant_id,
        title=body.title,
        description=body.description,
        notification_type=body.notification_type,
        params=body.params,
    )
    return {"data": {"status": "sent"}}

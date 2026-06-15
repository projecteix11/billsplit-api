from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse

from app.middleware.auth import require_auth
from app.middleware.tenant import require_feature
from app.models import CreateActivityEventBody
from app.services import activity as svc
from app.http_errors import internal_error

router = APIRouter()


@router.get("/activity-events")
def list_activity_events(
    request: Request,
    _user_id: str = Depends(require_auth),
    tenant_id: str = Depends(require_feature("activity")),
    category: str | None = None,
    tag: str | None = None,
    actor_type: str | None = None,
    table_number: int | None = None,
    q: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = Query(default=200, ge=1, le=500),
):
    try:
        events = svc.list_events(
            tenant_id=tenant_id,
            category=category,
            tag=tag,
            actor_type=actor_type,
            table_number=table_number,
            query=q,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
        )
        return {"data": [event.model_dump() for event in events], "error": None}
    except Exception as e:
        return internal_error(e)


@router.post("/activity-events", status_code=201)
def create_activity_event(
    request: Request,
    body: CreateActivityEventBody,
    _user_id: str = Depends(require_auth),
    tenant_id: str = Depends(require_feature("activity")),
):
    try:
        event = svc.create_manual_event(body, tenant_id=tenant_id, request=request)
        return JSONResponse(status_code=201, content={"data": event.model_dump(), "error": None})
    except Exception as e:
        return internal_error(e)

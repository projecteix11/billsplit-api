from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from app.logging.client import log_events

router = APIRouter()

# Browser logs are forwarded to Axiom by the server, so the diner PWA no longer
# needs a logging API key in its bundle (XC-3: VITE_LOGGING_API_KEY shipped a
# shared static credential to every anonymous client). The source is forced
# server-side so a caller cannot forge events as the API or staff apps.
_CLIENT_SOURCE = "📱 clients"
_MAX_BATCH = 50


class ClientLogEvent(BaseModel):
    type: str = "user_action"
    level: str = "info"
    module: str
    action: str
    http_method: str | None = None
    path: str | None = None
    status_code: int | None = None
    session_id: str | None = None
    request_id: str | None = None
    duration_ms: float | None = None
    metadata: dict | None = None


class ClientLogBatch(BaseModel):
    events: list[ClientLogEvent] = Field(default_factory=list, max_length=_MAX_BATCH)


@router.post("/client-logs", status_code=202)
def ingest_client_logs(request: Request, body: ClientLogBatch):
    """Accept a batch of anonymous client log events and forward them to Axiom.
    Never fails the caller: logging must not break the PWA. Unauthenticated by
    design (diners are anonymous); rate-limited by the global per-IP default
    (SlowAPIMiddleware) and source-stamped server-side."""
    client_ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or None
    events = [
        {**e.model_dump(exclude_none=True), "source": _CLIENT_SOURCE, "client_ip": client_ip}
        for e in body.events
    ]
    log_events(events)
    return {"data": {"accepted": len(events)}, "error": None}

"""Canonical log line middleware.

Produces exactly one log event per HTTP request. High-traffic read
routes are sampled to reduce storage cost.
"""

import random
import time
import uuid

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.logging import log_event, LogFactory

# Routes that are called on every page load — sample to 10 %
_SAMPLED_ROUTES: set[str] = {"/dishes", "/categories"}
_SAMPLE_RATE = 1


class RequestLoggingMiddleware(BaseHTTPMiddleware):

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        request.state.request_id = request_id
        start = time.perf_counter()

        ua = request.headers.get("user-agent", "").lower()
        backend_is_bot = any(k in ua for k in ("bot", "crawler", "spider", "curl", "postman", "python-requests", "httpx", "kuma"))
        backend_icon = "🤖" if backend_is_bot else "🐍"

        client_type = request.headers.get("x-client-type")
        if client_type:
            front_icon = "🤖" if client_type == "bot" else "🐍"
            source = f"{front_icon}{backend_icon} api"
        else:
            source = f"{backend_icon} api"

        correlation_id = request.headers.get("x-correlation-id")

        response = await call_next(request)
        response.headers["X-Request-Id"] = request_id

        duration_ms = (time.perf_counter() - start) * 1000
        path = request.url.path

        # Sampling: skip most successful reads on high-traffic routes
        if (
            request.method == "GET"
            and path in _SAMPLED_ROUTES
            and response.status_code < 400
            and random.random() > _SAMPLE_RATE
        ):
            return response

        user_id = getattr(request.state, "user_id", None)
        client_ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (request.client.host if request.client else None)
        event = LogFactory.canonical_line(
            method=request.method,
            path=path,
            status_code=response.status_code,
            duration_ms=duration_ms,
            user_id=user_id,
            request_id=request_id,
            client_ip=client_ip,
            source=source,
            correlation_id=correlation_id,
        )
        log_event(event)
        return response

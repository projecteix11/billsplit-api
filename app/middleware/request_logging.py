import random
import time
import uuid

from fastapi import Request
from starlette.types import ASGIApp, Scope, Receive, Send

from app.logging import log_event, LogFactory

# Routes that are called on every page load — sample to 10 %
_SAMPLED_ROUTES: set[str] = {"/dishes", "/categories"}
_SAMPLE_RATE = 1


class RequestLoggingMiddleware:

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
        
        # Inject request_id into state/scope so other handlers can access it
        if "state" not in scope:
            scope["state"] = {}
        scope["state"]["request_id"] = request_id

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
        
        status_code = [200]
        
        async def send_wrapper(message) -> None:
            if message["type"] == "http.response.start":
                status_code[0] = message["status"]
                # Add X-Request-Id to response headers
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode()))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            path = request.url.path

            # Sampling: skip most successful reads on high-traffic routes
            if (
                request.method == "GET"
                and path in _SAMPLED_ROUTES
                and status_code[0] < 400
                and random.random() > _SAMPLE_RATE
            ):
                pass
            else:
                user_id = getattr(request.state, "user_id", None)
                client_ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (request.client.host if request.client else None)
                event = LogFactory.canonical_line(
                    method=request.method,
                    path=path,
                    status_code=status_code[0],
                    duration_ms=duration_ms,
                    user_id=user_id,
                    request_id=request_id,
                    client_ip=client_ip,
                    source=source,
                    correlation_id=correlation_id,
                )
                log_event(event)


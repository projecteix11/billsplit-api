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
_SAMPLED_ROUTES: set[str] = {"/api/dishes", "/api/categories"}
_SAMPLE_RATE = 1


class RequestLoggingMiddleware(BaseHTTPMiddleware):

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        start = time.perf_counter()

        response = await call_next(request)

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
        event = LogFactory.canonical_line(
            method=request.method,
            path=path,
            status_code=response.status_code,
            duration_ms=duration_ms,
            user_id=user_id,
            request_id=request_id,
        )
        log_event(event)
        return response

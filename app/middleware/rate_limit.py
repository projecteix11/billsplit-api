import os

from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

_enabled = os.getenv("APP_ENV", "production") != "local"


def _client_ip(request: Request) -> str:
    """Rate-limit key = the real client IP. Behind Vercel/any proxy the socket
    peer is the proxy, so `get_remote_address` would bucket every user into one
    key (global throttling / no real per-client limit). Use the first hop of
    X-Forwarded-For instead — the same source the request logger trusts —
    falling back to the peer address when the header is absent (e.g. local dev)."""
    xff = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    return xff or get_remote_address(request)


limiter = Limiter(
    key_func=_client_ip,
    default_limits=["60/minute"],
    enabled=_enabled,
)


def rate_limit_exceeded_handler(_request: Request, exc: RateLimitExceeded):
    retry_after = exc.detail.split(" ")[-1] if exc.detail else "60"
    return JSONResponse(
        status_code=429,
        content={"data": None, "error": "Rate limit exceeded. Try again later."},
        headers={"Retry-After": retry_after},
    )

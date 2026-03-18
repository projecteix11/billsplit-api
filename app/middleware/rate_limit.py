from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address


def get_real_ip(request: Request) -> str:
    """Return the client IP, respecting X-Forwarded-For from a trusted proxy.

    When the API runs behind Nginx/Caddy/a cloud load balancer, request.client.host
    is always the proxy IP. Reading X-Forwarded-For gives us the actual client IP
    so that rate limiting is per-user, not per-proxy.

    Note: only enable this if the proxy strips untrusted X-Forwarded-For headers
    before adding its own. Otherwise clients can spoof their IP.
    """
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return get_remote_address(request)


limiter = Limiter(
    key_func=get_real_ip,
    default_limits=["10/minute"],
)


def rate_limit_exceeded_handler(_request: Request, exc: RateLimitExceeded):
    retry_after = exc.detail.split(" ")[-1] if exc.detail else "60"
    return JSONResponse(
        status_code=429,
        content={"data": None, "error": "Rate limit exceeded. Try again later."},
        headers={"Retry-After": retry_after},
    )

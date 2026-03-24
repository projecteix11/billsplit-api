from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=["60/minute"],
)


def rate_limit_exceeded_handler(_request: Request, exc: RateLimitExceeded):
    retry_after = exc.detail.split(" ")[-1] if exc.detail else "60"
    return JSONResponse(
        status_code=429,
        content={"data": None, "error": "Rate limit exceeded. Try again later."},
        headers={"Retry-After": retry_after},
    )

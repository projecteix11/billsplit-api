from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.db import supabase
from app.logging import log_event, LogFactory

PROTECTED_ROUTES = [
    ("GET", "/api/orders"),
    ("PATCH", "/api/order-items/"),  # kitchen-status prefix check
]


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Only protect specific routes
        path = request.url.path
        method = request.method

        needs_auth = (
            (method == "GET" and path == "/api/orders") or
            (method == "PATCH" and "/kitchen-status" in path) or
            (method in ("POST", "PATCH", "DELETE") and path.startswith("/api/dishes")) or
            (method == "POST" and path == "/api/allergens") or
            (method in ("POST", "DELETE") and path.startswith("/api/custom-dishes"))
        )

        if needs_auth:
            header = request.headers.get("Authorization", "")
            if not header.startswith("Bearer "):
                log_event(LogFactory.auth_event(
                    "auth_missing_header",
                    metadata={"path": path, "method": method},
                ))
                return JSONResponse(
                    status_code=401,
                    content={"data": None, "error": "Missing or invalid Authorization header"},
                )
            token = header[7:]
            try:
                user_id, tenant_id = supabase.verify_token_full(token)
                request.state.user_id = user_id
                request.state.tenant_id = tenant_id
            except Exception:
                log_event(LogFactory.auth_event(
                    "auth_token_invalid",
                    metadata={"path": path, "method": method},
                ))
                return JSONResponse(
                    status_code=401,
                    content={"data": None, "error": "Invalid or expired token"},
                )

        return await call_next(request)


class AuthError(Exception):
    def __init__(self, message: str):
        self.message = message


async def auth_error_handler(_request: Request, exc: AuthError):
    return JSONResponse(
        status_code=401,
        content={"data": None, "error": exc.message},
    )


def require_auth(request: Request) -> str:
    """Dependency that verifies the Bearer token and returns the user ID."""
    # Reuse result already stored by AuthMiddleware to avoid a second Supabase call
    user_id = getattr(request.state, "user_id", None)
    if user_id:
        return user_id
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise AuthError("Missing or invalid Authorization header")
    token = header[7:]
    try:
        user_id, tenant_id = supabase.verify_token_full(token)
        request.state.user_id = user_id
        request.state.tenant_id = tenant_id
        return user_id
    except Exception:
        raise AuthError("Invalid or expired token")

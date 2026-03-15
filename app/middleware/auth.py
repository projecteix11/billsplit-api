from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.db import supabase

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
            (method == "PATCH" and "/kitchen-status" in path)
        )

        if needs_auth:
            header = request.headers.get("Authorization", "")
            if not header.startswith("Bearer "):
                return JSONResponse(
                    status_code=401,
                    content={"data": None, "error": "Missing or invalid Authorization header"},
                )
            token = header[7:]
            try:
                user_id = supabase.verify_token(token)
                request.state.user_id = user_id
            except Exception:
                return JSONResponse(
                    status_code=401,
                    content={"data": None, "error": "Invalid or expired token"},
                )

        return await call_next(request)


def require_auth(request: Request) -> str:
    """Dependency that verifies the Bearer token and returns the user ID."""
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid Authorization header",
        )
    token = header[7:]
    try:
        return supabase.verify_token(token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

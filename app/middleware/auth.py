from fastapi import Request
from fastapi.responses import JSONResponse

from app.db import supabase


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
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        raise AuthError("Missing or invalid Authorization header")
    token = header[7:]
    try:
        return supabase.verify_token(token)
    except Exception:
        raise AuthError("Invalid or expired token")

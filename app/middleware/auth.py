import os

from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.db import supabase
from app.logging import log_event, LogFactory
from app.services.guest_session import verify_guest_token, GuestTokenError

# XM-6 rollout switch. Grace period (default): customer mutations without a
# known principal are allowed but logged, so token adoption can be monitored.
# Flip to "true" to hard-fail (401) once the clients are confirmed sending tokens.
ENFORCE_GUEST_TOKEN = os.getenv("ENFORCE_GUEST_TOKEN", "false").lower() == "true"

PROTECTED_ROUTES = [
    ("GET", "/orders"),
    ("PATCH", "/order-items/"),  # kitchen-status prefix check
]


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Only protect specific routes
        path = request.url.path
        method = request.method

        needs_auth = (
            (method == "GET" and path in ("/orders", "/reservations", "/me")) or
            (method == "PATCH" and ("/kitchen-status" in path or path.startswith("/reservations/"))) or
            (method in ("POST", "PATCH", "DELETE") and path.startswith("/dishes")) or
            (method == "POST" and path == "/allergens") or
            (method in ("POST", "DELETE") and path.startswith("/custom-dishes"))
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
                user_id, tenant_id, role = supabase.verify_token_full(token)
                request.state.user_id = user_id
                request.state.role = role
                if role == "developer":
                    dev_tenant_id = request.headers.get("X-Tenant-Id")
                    if dev_tenant_id:
                        request.state.tenant_id = dev_tenant_id
                    else:
                        dev_slug = request.headers.get("X-Tenant-Slug")
                        from app.middleware.tenant import _resolve_slug
                        request.state.tenant_id = _resolve_slug(dev_slug) if dev_slug else None
                else:
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


def require_customer_principal(request: Request) -> None:
    """Customer mutation guard (XM-6). The caller must be a known principal —
    either staff (Supabase Bearer JWT) or a diner holding a valid guest session
    token (X-Guest-Token). During the grace period, a request with neither is
    allowed but logged so adoption can be tracked; set ENFORCE_GUEST_TOKEN=true
    to hard-fail (401). Tenant resolution still happens in get_current_tenant;
    this only asserts *who* is calling."""
    # Staff path: a valid Supabase JWT.
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        try:
            supabase.verify_token_full(auth_header[7:])
            return
        except Exception:
            pass

    # Diner path: a valid guest session token.
    guest_token = request.headers.get("X-Guest-Token", "")
    if guest_token:
        try:
            verify_guest_token(guest_token)
            return
        except GuestTokenError:
            pass

    # Neither — grace by default, hard-fail when enforcement is switched on.
    log_event(LogFactory.auth_event(
        "customer_mutation_no_principal",
        metadata={"path": request.url.path, "method": request.method, "enforced": ENFORCE_GUEST_TOKEN},
    ))
    if ENFORCE_GUEST_TOKEN:
        raise AuthError("A guest session token (or staff auth) is required")


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
        user_id, tenant_id, role = supabase.verify_token_full(token)
        request.state.user_id = user_id
        request.state.tenant_id = tenant_id
        request.state.role = role
        return user_id
    except Exception:
        raise AuthError("Invalid or expired token")

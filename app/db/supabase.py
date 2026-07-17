import os
import time

from supabase import Client, create_client

_client: Client | None = None
_base_url: str = ""
_api_key: str = ""

_TOKEN_CACHE: dict[str, tuple[str, str, str, float]] = {}
_TOKEN_CACHE_TTL = 120.0


def init() -> None:
    global _client, _base_url, _api_key

    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
    if not url or not key:
        raise RuntimeError("missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY")

    _base_url = url
    _api_key = key
    _client = create_client(url, key)


def get_client() -> Client:
    if _client is None:
        raise RuntimeError("supabase client not initialized")
    return _client


def get_base_url() -> str:
    return _base_url


def get_api_key() -> str:
    return _api_key


def create_auth_user(email: str, password: str, user_metadata: dict) -> dict:
    try:
        response = get_client().auth.admin.create_user({
            "email": email,
            "password": password,
            "email_confirm": True,
            "user_metadata": user_metadata,
        })
        user = response.user
        return {"id": str(user.id), "email": user.email}
    except Exception as e:
        raise RuntimeError(f"failed to create user: {e}")


def delete_auth_user(user_id: str) -> None:
    try:
        get_client().auth.admin.delete_user(user_id)
    except Exception as e:
        raise RuntimeError(f"failed to delete user: {e}")


def verify_token(token: str) -> str:
    user_id, _, _ = verify_token_full(token)
    return user_id


def is_platform_admin(user_id: str) -> bool:
    """True if user_id is a row in public.platform_admins. Uses the service-role
    client (bypasses RLS) so the check is authoritative regardless of the
    caller's own row visibility. This is the same membership the adminPanel's
    is_platform_admin() SQL helper gates on."""
    if not user_id:
        return False
    rows = (
        get_client()
        .table("platform_admins")
        .select("user_id")
        .eq("user_id", user_id)
        .limit(1)
        .execute()
        .data
    )
    return bool(rows)


def verify_token_full(token: str) -> tuple[str, str, str]:
    """Verify token and return (user_id, tenant_id, role). Result is cached for 2 minutes.

    Authorization signals (role, tenant_id) are derived ONLY from server-controlled
    sources: the user_roles table and platform_admins membership. user_metadata is
    self-editable by the user via GoTrue (auth.updateUser), so it is never trusted
    here for role or tenant — doing so let a self-registered user grant themselves
    staff/developer privileges on an arbitrary tenant (Master Ecosystem Report XC-2).
    A principal with no enabled user_roles row and no platform_admins membership is
    unprivileged: role "user", no tenant.
    """
    cached = _TOKEN_CACHE.get(token)
    if cached and time.monotonic() < cached[3]:
        return cached[0], cached[1], cached[2]

    try:
        response = get_client().auth.get_user(token)
    except Exception:
        _TOKEN_CACHE.pop(token, None)
        raise ValueError("invalid or expired token")

    user = response.user
    if not user or not user.id:
        raise ValueError("invalid token: no user id")

    user_id = str(user.id)

    # Staff: role + tenant come from an enabled user_roles row (authoritative).
    # Checked first because it is the common case and a single query.
    rows = (
        get_client()
        .table("user_roles")
        .select("tenant_id,role")
        .eq("user_id", user_id)
        .eq("enabled", True)
        .limit(1)
        .execute()
        .data
    )
    if rows:
        tenant_id = str(rows[0].get("tenant_id", ""))
        role = str(rows[0].get("role", "") or "user")
    elif is_platform_admin(user_id):
        # Platform admins operate across the platform and have no tenant.
        tenant_id = ""
        role = "developer"
    else:
        # Unprivileged authenticated principal (e.g. a self-registered diner).
        tenant_id = ""
        role = "user"

    _TOKEN_CACHE[token] = (user_id, tenant_id, role, time.monotonic() + _TOKEN_CACHE_TTL)
    return user_id, tenant_id, role

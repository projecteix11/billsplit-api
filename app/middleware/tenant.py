import time
from urllib.parse import urlparse

from fastapi import Depends, HTTPException, Request

from app.db.supabase import get_client, verify_token_full

_SLUG_CACHE: dict[str, tuple[str, float]] = {}
_FEATURES_CACHE: dict[str, tuple[dict, float]] = {}
_CACHE_TTL = 300.0  # 5 minutes

# Subdomains reserved for platform services — never treated as tenant slugs
_RESERVED_SLUGS = frozenset({"management", "api", "admin", "www", "app", "landing", "status", "billing"})


def _resolve_slug(slug: str) -> str | None:
    cached = _SLUG_CACHE.get(slug)
    if cached and time.monotonic() - cached[1] < _CACHE_TTL:
        return cached[0] or None
    rows = get_client().table("tenants").select("id").eq("slug", slug).eq("is_active", True).limit(1).execute().data or []
    tenant_id = rows[0]["id"] if rows else ""
    _SLUG_CACHE[slug] = (tenant_id, time.monotonic())
    return tenant_id or None


def _parse_slug_from_origin(origin: str | None) -> str | None:
    if not origin:
        return None
    hostname = urlparse(origin).hostname or ""
    parts = hostname.split(".")
    # {slug}.gobbly.app (production) or {slug}.lvh.me (local dev via hosts file)
    if len(parts) >= 2 and parts[-2] in ("gobbly", "lvh"):
        slug = parts[0]
        return None if slug in _RESERVED_SLUGS else slug
    return None


def _get_tenant_features(tenant_id: str) -> dict:
    cached = _FEATURES_CACHE.get(tenant_id)
    if cached and time.monotonic() - cached[1] < _CACHE_TTL:
        return cached[0]
    rows = get_client().table("tenants").select("features").eq("id", tenant_id).limit(1).execute().data or []
    features = rows[0]["features"] if rows else {}
    _FEATURES_CACHE[tenant_id] = (features or {}, time.monotonic())
    return features or {}


def require_feature(key: str):
    async def dep(tenant_id: str = Depends(get_current_tenant)) -> str:
        features = _get_tenant_features(tenant_id)
        if not features.get(key):
            raise HTTPException(status_code=403, detail=f"Feature '{key}' not enabled for this tenant")
        return tenant_id
    return dep


async def get_current_tenant(request: Request) -> str:
    """FastAPI dependency that resolves the current tenant_id.

    Priority:
      1. JWT already verified by AuthMiddleware or require_auth → use state
      2. Bearer token in header → verify and extract tenant_id
      3. X-Tenant-Slug header → slug lookup in DB
      4. Origin/Referer header → parse slug → DB lookup
      5. 404
    """
    # 1. Already resolved (auth middleware ran for this route)
    tenant_id = getattr(request.state, "tenant_id", None)
    if tenant_id:
        return tenant_id

    # 2. Bearer token present but not yet verified (route outside AuthMiddleware list)
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        try:
            user_id, tenant_id, role = verify_token_full(auth_header[7:])
            if tenant_id:
                request.state.user_id = user_id
                request.state.tenant_id = tenant_id
                request.state.role = role
                return tenant_id
        except Exception:
            raise HTTPException(status_code=401, detail="Invalid or expired token")

    # 3. X-Tenant-Slug header → resolve slug against DB
    tenant_slug_header = request.headers.get("X-Tenant-Slug")
    if tenant_slug_header:
        tenant_id = _resolve_slug(tenant_slug_header)
        if tenant_id:
            request.state.tenant_id = tenant_id
            return tenant_id

    # 4. Public route — resolve from Origin header (browser-enforced, JS cannot spoof cross-origin)
    origin = request.headers.get("origin") or request.headers.get("referer")
    slug = _parse_slug_from_origin(origin)
    if slug:
        tenant_id = _resolve_slug(slug)
        if tenant_id:
            return tenant_id

    raise HTTPException(status_code=404, detail="Tenant not found")

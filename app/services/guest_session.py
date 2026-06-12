"""Guest session tokens (Master Ecosystem Report XM-6).

A diner has no credential today: the frontend identifies them by a free-text
name and a spoofable `X-Tenant-Slug` header, and tenant context is lost across
the Redsys redirect. This issues a short-lived, signed token at QR-scan time,
bound to the tenant + table (+ order once it exists), so the API can derive the
tenant from a server-trusted claim instead of a client-supplied header.

The token is a compact HS256 JWT signed with `GUEST_SESSION_SECRET` (stdlib
HMAC — no extra dependency). It is a bearer credential for the *customer* path
only; staff continue to use their Supabase JWT. There is no live-money or admin
capability in the claims — only tenant/table/order scoping.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time

# A dining session — long enough to order, eat, and split the bill, short enough
# that a leaked token isn't useful tomorrow.
GUEST_SESSION_TTL = 6 * 60 * 60  # seconds

_HEADER = {"alg": "HS256", "typ": "JWT"}


class GuestTokenError(Exception):
    """Raised when a guest token is missing, malformed, tampered, or expired."""


def _secret() -> bytes:
    secret = os.getenv("GUEST_SESSION_SECRET", "")
    if not secret:
        # Fail loudly rather than signing with an empty/guessable key — same
        # stance as redsys-sign's REDSYS_SECRET.
        raise GuestTokenError("GUEST_SESSION_SECRET is not configured")
    return secret.encode("utf-8")


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(segment: str) -> bytes:
    pad = "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(segment + pad)


def _sign(signing_input: bytes) -> str:
    sig = hmac.new(_secret(), signing_input, hashlib.sha256).digest()
    return _b64url_encode(sig)


def issue_guest_token(
    tenant_id: str,
    table_id: str,
    order_id: str | None = None,
    guest_id: str | None = None,
    ttl_seconds: int = GUEST_SESSION_TTL,
) -> tuple[str, int]:
    """Return (token, exp_epoch_seconds). Tenant/table are server-derived from
    the scanned resource by the caller — never from client input."""
    now = int(time.time())
    exp = now + ttl_seconds
    payload: dict[str, object] = {"tid": tenant_id, "tbl": table_id, "iat": now, "exp": exp}
    if order_id:
        payload["oid"] = order_id
    if guest_id:
        payload["gid"] = guest_id

    header_seg = _b64url_encode(json.dumps(_HEADER, separators=(",", ":")).encode())
    payload_seg = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode())
    signing_input = f"{header_seg}.{payload_seg}".encode("ascii")
    return f"{header_seg}.{payload_seg}.{_sign(signing_input)}", exp


def open_guest_session(table_id: str) -> dict | None:
    """Issue a guest token for a scanned table. The tenant is read from the
    table row (server-trusted, never client-supplied); the active order id, if
    any, is bound into the token so later mutations can be cross-checked.
    Returns None when the table is unknown or inactive."""
    from app.db.supabase import get_client  # local import keeps the crypto unit DB-free

    rows = (
        get_client()
        .table("restaurant_tables")
        .select("id, tenant_id, is_active, active_order_id")
        .eq("id", table_id)
        .limit(1)
        .execute()
        .data
        or []
    )
    if not rows or not rows[0].get("is_active", True):
        return None

    row = rows[0]
    order_id = str(row["active_order_id"]) if row.get("active_order_id") else None
    token, exp = issue_guest_token(str(row["tenant_id"]), str(row["id"]), order_id=order_id)
    return {"token": token, "expiresAt": exp, "tenantId": str(row["tenant_id"])}


def verify_guest_token(token: str) -> dict:
    """Validate signature + expiry and return the claims dict. Raises
    GuestTokenError on any problem (never returns partial/unverified claims)."""
    if not token or token.count(".") != 2:
        raise GuestTokenError("malformed token")
    header_seg, payload_seg, sig_seg = token.split(".")
    signing_input = f"{header_seg}.{payload_seg}".encode("ascii")

    expected = _sign(signing_input)
    if not hmac.compare_digest(expected, sig_seg):
        raise GuestTokenError("bad signature")

    try:
        claims = json.loads(_b64url_decode(payload_seg))
    except Exception as exc:
        raise GuestTokenError("undecodable payload") from exc

    if not isinstance(claims, dict) or "tid" not in claims or "exp" not in claims:
        raise GuestTokenError("missing required claims")
    if int(claims["exp"]) < int(time.time()):
        raise GuestTokenError("expired token")

    return claims

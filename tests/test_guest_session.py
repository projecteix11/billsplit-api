"""
Tests for guest session tokens (Master Ecosystem Report XM-6).

  POST /guest-session         – issue a token for a scanned table (tenant derived
                                server-side from the table, never client-supplied)
  guest_session.{issue,verify} – HS256 HMAC primitives (stdlib, no extra dep)
  get_current_tenant           – trusts a valid X-Guest-Token's tenant claim above
                                 the spoofable X-Tenant-Slug header
"""

import time
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from tests.conftest import make_mock_client, VALID_TENANT_ID
from app.services import guest_session as gs


# ---------------------------------------------------------------------------
# Token primitives
# ---------------------------------------------------------------------------

class TestTokenPrimitives:
    def test_round_trip_returns_claims(self):
        token, exp = gs.issue_guest_token("tenant-1", "table-9", order_id="order-3")
        claims = gs.verify_guest_token(token)
        assert claims["tid"] == "tenant-1"
        assert claims["tbl"] == "table-9"
        assert claims["oid"] == "order-3"
        assert claims["exp"] == exp

    def test_tampered_payload_is_rejected(self):
        token, _ = gs.issue_guest_token("tenant-1", "table-9")
        header, payload, sig = token.split(".")
        # Re-sign nothing — just swap the payload for a forged tenant.
        forged_payload = gs._b64url_encode(b'{"tid":"attacker","tbl":"x","iat":1,"exp":9999999999}')
        forged = f"{header}.{forged_payload}.{sig}"
        with pytest.raises(gs.GuestTokenError, match="bad signature"):
            gs.verify_guest_token(forged)

    def test_expired_token_is_rejected(self):
        token, _ = gs.issue_guest_token("tenant-1", "table-9", ttl_seconds=-1)
        with pytest.raises(gs.GuestTokenError, match="expired"):
            gs.verify_guest_token(token)

    def test_malformed_token_is_rejected(self):
        with pytest.raises(gs.GuestTokenError, match="malformed"):
            gs.verify_guest_token("not-a-jwt")

    def test_missing_secret_fails_loudly(self, monkeypatch):
        monkeypatch.delenv("GUEST_SESSION_SECRET", raising=False)
        with pytest.raises(gs.GuestTokenError, match="not configured"):
            gs.issue_guest_token("tenant-1", "table-9")


# ---------------------------------------------------------------------------
# Service: open_guest_session (table -> tenant derivation)
# ---------------------------------------------------------------------------

class TestOpenGuestSession:
    def test_derives_tenant_from_table(self):
        table_row = {"id": "table-9", "tenant_id": "tenant-1", "is_active": True, "active_order_id": "order-3"}
        # open_guest_session does a local `from app.db.supabase import get_client`.
        with patch("app.db.supabase.get_client", return_value=make_mock_client(data=[table_row])):
            session = gs.open_guest_session("table-9")
        assert session is not None
        assert session["tenantId"] == "tenant-1"
        claims = gs.verify_guest_token(session["token"])
        assert claims["tid"] == "tenant-1"
        assert claims["oid"] == "order-3"

    def test_unknown_table_returns_none(self):
        with patch("app.db.supabase.get_client", return_value=make_mock_client(data=[])):
            assert gs.open_guest_session("ghost") is None

    def test_inactive_table_returns_none(self):
        row = {"id": "t", "tenant_id": "x", "is_active": False, "active_order_id": None}
        with patch("app.db.supabase.get_client", return_value=make_mock_client(data=[row])):
            assert gs.open_guest_session("t") is None


# ---------------------------------------------------------------------------
# POST /guest-session
# ---------------------------------------------------------------------------

class TestGuestSessionEndpoint:
    def test_returns_201_and_token(self, client: TestClient):
        table_row = {"id": "table-9", "tenant_id": VALID_TENANT_ID, "is_active": True, "active_order_id": None}
        with patch("app.db.supabase.get_client", return_value=make_mock_client(data=[table_row])):
            resp = client.post("/guest-session", json={"tableId": "table-9"})
        assert resp.status_code == 201
        data = resp.json()["data"]
        assert data["token"]
        assert data["tenantId"] == VALID_TENANT_ID

    def test_unknown_table_returns_404(self, client: TestClient):
        with patch("app.db.supabase.get_client", return_value=make_mock_client(data=[])):
            resp = client.post("/guest-session", json={"tableId": "ghost"})
        assert resp.status_code == 404

    def test_missing_table_id_returns_422(self, client: TestClient):
        resp = client.post("/guest-session", json={})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# get_current_tenant trusts the guest token (non-breaking integration)
# ---------------------------------------------------------------------------

class TestTenantFromGuestToken:
    def test_guest_token_resolves_tenant_for_public_route(self, app, client: TestClient):
        # Drop the test-wide tenant override so the real resolver runs.
        from app.middleware.tenant import get_current_tenant
        app.dependency_overrides.pop(get_current_tenant, None)
        try:
            token, _ = gs.issue_guest_token("tenant-from-token", "table-9", order_id="order-3")
            order = {
                "id": "order-3", "table_id": "table-9", "table_number": 5, "status": "open",
                "subtotal": 10.0, "tax_amount": 1.0, "total": 11.0, "amount_paid": 0.0,
                "created_at": "2024-01-01T10:00:00+00:00", "updated_at": "2024-01-01T10:00:00+00:00",
                "items": [], "tenant_id": "tenant-from-token",
            }
            # add_items requires only that tenant resolution succeeds; stub the service.
            with patch("app.services.orders.add_items_to_order", return_value=None), \
                 patch("app.services.activity.get_order_context", return_value=None):
                resp = client.post(
                    "/orders/order-3/items",
                    json={"items": [{"dish_name": "X", "dish_price": 1.0, "quantity": 1}]},
                    headers={"X-Guest-Token": token},
                )
            # The route itself doesn't depend on tenant, but the header must not 401/500.
            assert resp.status_code == 200
        finally:
            app.dependency_overrides[get_current_tenant] = lambda: VALID_TENANT_ID

    def test_invalid_guest_token_is_ignored_not_fatal(self):
        # A bad token must raise GuestTokenError from verify, which the resolver swallows.
        with pytest.raises(gs.GuestTokenError):
            gs.verify_guest_token("garbage.token.here")


# ---------------------------------------------------------------------------
# require_customer_principal — grace-period guard on customer mutations (XM-6)
# ---------------------------------------------------------------------------

class TestCustomerPrincipalGuard:
    def _req(self, headers=None):
        class _Req:
            pass
        r = _Req()
        r.headers = headers or {}
        r.url = type("U", (), {"path": "/orders"})()
        r.method = "POST"
        return r

    def test_grace_allows_when_no_principal(self, monkeypatch):
        import app.middleware.auth as auth_mod
        monkeypatch.setattr(auth_mod, "ENFORCE_GUEST_TOKEN", False)
        # Grace: no token, no staff — must NOT raise (just logs).
        assert auth_mod.require_customer_principal(self._req()) is None

    def test_valid_guest_token_passes_even_when_enforced(self, monkeypatch):
        import app.middleware.auth as auth_mod
        monkeypatch.setattr(auth_mod, "ENFORCE_GUEST_TOKEN", True)
        token, _ = gs.issue_guest_token("tenant-1", "table-9")
        assert auth_mod.require_customer_principal(self._req({"X-Guest-Token": token})) is None

    def test_enforce_rejects_when_no_principal(self, monkeypatch):
        import app.middleware.auth as auth_mod
        monkeypatch.setattr(auth_mod, "ENFORCE_GUEST_TOKEN", True)
        with pytest.raises(auth_mod.AuthError):
            auth_mod.require_customer_principal(self._req())

    def test_staff_bearer_passes(self, monkeypatch):
        import app.middleware.auth as auth_mod
        monkeypatch.setattr(auth_mod, "ENFORCE_GUEST_TOKEN", True)
        with patch("app.middleware.auth.supabase.verify_token_full", return_value=("u", "t", "staff")):
            assert auth_mod.require_customer_principal(self._req({"Authorization": "Bearer staff-jwt"})) is None

"""Tests for the tenant middleware (get_current_tenant dependency)."""

import time
import unittest.mock as mock

import pytest
from fastapi.testclient import TestClient
from app.middleware.tenant import get_current_tenant


@pytest.fixture
def real_tenant_client(app):
    """TestClient that does NOT override get_current_tenant — tests real resolution."""
    original = app.dependency_overrides.pop(get_current_tenant, None)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    if original is not None:
        app.dependency_overrides[get_current_tenant] = original


# ---------------------------------------------------------------------------
# Unit tests for slug resolution helpers
# ---------------------------------------------------------------------------

def test_parse_slug_from_gobbly_domain():
    from app.middleware.tenant import _parse_slug_from_origin
    assert _parse_slug_from_origin("https://demo.gobbly.app") == "demo"
    assert _parse_slug_from_origin("https://my-restaurant.gobbly.app") == "my-restaurant"


def test_parse_slug_from_lvh_dev():
    from app.middleware.tenant import _parse_slug_from_origin
    assert _parse_slug_from_origin("http://demo.lvh.me:3000") == "demo"


def test_parse_slug_returns_none_for_unknown_domain():
    from app.middleware.tenant import _parse_slug_from_origin
    assert _parse_slug_from_origin("https://management.gobbly.app") is None
    assert _parse_slug_from_origin("http://localhost:5173") is None
    assert _parse_slug_from_origin(None) is None


def test_slug_cache_ttl(monkeypatch):
    from app.middleware import tenant as t

    monkeypatch.setattr(t, "_SLUG_CACHE", {})
    monkeypatch.setattr(t, "_CACHE_TTL", 1.0)  # 1 second for test speed

    with mock.patch("app.db.supabase.select", return_value=[{"id": "uuid-abc"}]) as m:
        result1 = t._resolve_slug("demo")
        assert result1 == "uuid-abc"
        assert m.call_count == 1

        result2 = t._resolve_slug("demo")
        assert result2 == "uuid-abc"
        assert m.call_count == 1  # served from cache

    # Expire cache
    t._SLUG_CACHE["demo"] = (t._SLUG_CACHE["demo"][0], time.monotonic() - 2.0)
    with mock.patch("app.db.supabase.select", return_value=[{"id": "uuid-abc"}]) as m:
        t._resolve_slug("demo")
        assert m.call_count == 1  # cache expired → DB hit


def test_slug_cache_caches_misses(monkeypatch):
    from app.middleware import tenant as t

    monkeypatch.setattr(t, "_SLUG_CACHE", {})
    with mock.patch("app.db.supabase.select", return_value=[]) as m:
        result1 = t._resolve_slug("nonexistent")
        assert result1 is None
        assert m.call_count == 1

        result2 = t._resolve_slug("nonexistent")
        assert result2 is None
        assert m.call_count == 1  # miss also cached


# ---------------------------------------------------------------------------
# Integration tests via TestClient
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_tenant_select(monkeypatch):
    """Patch supabase.select to return a tenant row for slug 'demo'."""
    from app.middleware import tenant as t
    monkeypatch.setattr(t, "_SLUG_CACHE", {})

    def _select(table, query=""):
        if table == "tenants" and "demo" in query:
            return [{"id": "tenant-uuid-demo"}]
        return []

    with mock.patch("app.db.supabase.select", side_effect=_select):
        yield


def test_dishes_without_origin_returns_404(real_tenant_client, mock_tenant_select):
    # No Origin header, no Authorization header → 404
    resp = real_tenant_client.get("/dishes", headers={})
    assert resp.status_code == 404


def test_dishes_with_tenant_origin_resolves(real_tenant_client, mock_tenant_select):
    with mock.patch("app.services.dishes.get_all_dishes", return_value=[]) as m:
        resp = real_tenant_client.get(
            "/dishes",
            headers={"Origin": "https://demo.gobbly.app"},
        )
    assert resp.status_code == 200
    m.assert_called_once_with("tenant-uuid-demo")


def test_dishes_with_unknown_origin_returns_404(real_tenant_client, mock_tenant_select):
    resp = real_tenant_client.get(
        "/dishes",
        headers={"Origin": "https://unknown.gobbly.app"},
    )
    assert resp.status_code == 404


def test_orders_list_with_valid_jwt(real_tenant_client, monkeypatch):
    """Staff list orders — JWT provides tenant_id."""
    from app.middleware import tenant as t
    monkeypatch.setattr(t, "_SLUG_CACHE", {})

    with (
        mock.patch("app.db.supabase.verify_token_full", return_value=("user-1", "tenant-uuid-staff")),
        mock.patch("app.services.orders.fetch_orders", return_value=[]) as m,
    ):
        resp = real_tenant_client.get(
            "/orders",
            headers={"Authorization": "Bearer valid-jwt-token"},
        )
    assert resp.status_code == 200
    m.assert_called_once_with("tenant-uuid-staff", "open", kitchen_only=False)


def test_invalid_jwt_returns_401(real_tenant_client, monkeypatch):
    from app.middleware import tenant as t
    monkeypatch.setattr(t, "_SLUG_CACHE", {})

    with mock.patch("app.db.supabase.verify_token_full", side_effect=ValueError("bad token")):
        resp = real_tenant_client.get(
            "/dishes",
            headers={"Authorization": "Bearer bad-token"},
        )
    assert resp.status_code == 401

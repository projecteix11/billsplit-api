"""
Shared fixtures and test setup for the BillSplit API test suite.

Strategy:
- The app talks to Supabase via the `app.db.supabase` module (get_client() fluent builder).
- We patch get_client() at the service/router level so no real HTTP calls are made.
- The app's `supabase.init()` call at import time requires env vars; we stub them out
  with monkeypatching before the app is created.
- Rate-limit state is reset between tests via a fresh limiter storage override.
"""

import sys
import os
import types
import pytest
from unittest.mock import MagicMock

# Stub out axiom_py BEFORE any app code is imported so the logging module
# can be loaded without the real axiom-py package being installed.
if "axiom_py" not in sys.modules:
    _axiom_stub = types.ModuleType("axiom_py")
    _axiom_stub.Client = type("Client", (), {  # type: ignore[attr-defined]
        "__init__": lambda self, **kw: None,
        "ingest_events": lambda self, **kw: None,
    })
    sys.modules["axiom_py"] = _axiom_stub

# Provide dummy env vars BEFORE importing the app so supabase.init() doesn't fail.
os.environ.setdefault("SUPABASE_URL", "http://test.supabase.local")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
os.environ.setdefault("GUEST_SESSION_SECRET", "test-guest-session-secret")

from fastapi.testclient import TestClient
from app.middleware.tenant import get_current_tenant
import app.middleware.tenant as _tenant_middleware


# ---------------------------------------------------------------------------
# Mock builder for supabase-py fluent client
# ---------------------------------------------------------------------------

def make_mock_client(data=None):
    """Mock of supabase Client that supports the fluent builder pattern.

    Every chained method returns the same mock object. .execute() returns a
    MagicMock with .data set to `data` (default: empty list).
    """
    mock_q = MagicMock()
    for method in [
        "table", "select", "eq", "neq", "gt", "gte", "lt", "lte",
        "in_", "ilike", "like", "order", "limit", "not_", "or_",
        "insert", "update", "delete", "upsert", "filter",
    ]:
        getattr(mock_q, method).return_value = mock_q
    mock_q.execute.return_value = MagicMock(data=data if data is not None else [])
    return mock_q

# ---------------------------------------------------------------------------
# Factories for common model dicts
# ---------------------------------------------------------------------------

def make_dish(**overrides) -> dict:
    base = {
        "id": "dish-1",
        "name": "Pizza Margherita",
        "description": "Classic tomato and mozzarella",
        "price": 12.50,
        "is_available": True,
        "category_id": "cat-1",
    }
    return {**base, **overrides}


def make_category(**overrides) -> dict:
    base = {
        "id": "cat-1",
        "name": "Pizzas",
        "sort_order": 1,
        "requires_kitchen": True,
    }
    return {**base, **overrides}


def make_order_item(**overrides) -> dict:
    base = {
        "id": "item-1",
        "order_id": "order-1",
        "dish_name": "Pizza Margherita",
        "dish_price": 12.50,
        "quantity": 2,
        "notes": None,
        "diner_name": "Cliente",
        "kitchen_status": "pending",
        "payment_status": "unassigned",
    }
    return {**base, **overrides}


def make_order(**overrides) -> dict:
    base = {
        "id": "order-1",
        "table_id": "table-1",
        "table_number": 5,
        "status": "open",
        "subtotal": 25.0,
        "tax_amount": 2.5,
        "total": 27.5,
        "created_at": "2024-01-01T10:00:00+00:00",
        "updated_at": "2024-01-01T10:00:00+00:00",
        "items": [],
        "tenant_id": VALID_TENANT_ID,
    }
    return {**base, **overrides}


def make_payment(**overrides) -> dict:
    base = {
        "id": "pay-1",
        "order_id": "order-1",
        "amount": 27.50,
        "tip_amount": 0.0,
        "total_charged": 27.50,
        "payment_method": "card",
        "status": "confirmed",
    }
    return {**base, **overrides}


# ---------------------------------------------------------------------------
# App + client fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def app():
    """Return the FastAPI application, initialised once per test session.

    supabase.init() and create_client are patched to no-ops so no real network
    calls occur.  get_current_tenant is overridden to return VALID_TENANT_ID so
    existing route tests don't need an Origin header or JWT.
    """
    import unittest.mock as mock
    with mock.patch("app.db.supabase.create_client", return_value=make_mock_client()):
        with mock.patch("app.db.supabase.init"):
            import app.db.supabase as sb
            sb._client = make_mock_client()
            sb._base_url = "http://test.supabase.local"
            sb._api_key = "test-service-role-key"

            # All features enabled in tests — avoids DB calls from _get_tenant_features
            _tenant_middleware._get_tenant_features = lambda _tid: {
                "reservations": True, "kitchen": True, "payments": True,
                "daily_menus": True, "campaigns": True, "qr_codes": True,
            }

            from main import app as fastapi_app
            fastapi_app.dependency_overrides[get_current_tenant] = lambda: VALID_TENANT_ID
            return fastapi_app


@pytest.fixture()
def client(app):
    """Return a fresh TestClient for each test."""
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# ---------------------------------------------------------------------------
# Rate limit reset
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Reset the in-memory rate-limit storage before every test.

    slowapi uses a single MemoryStorage instance on the Limiter object.
    Without this, tests that hit rate-limited endpoints accumulate counts
    across the session and start getting 429s.
    """
    from app.middleware.rate_limit import limiter
    limiter._storage.reset()
    yield


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

VALID_TOKEN = "valid-bearer-token"
VALID_USER_ID = "user-uuid-123"
VALID_TENANT_ID = "test-tenant-uuid"

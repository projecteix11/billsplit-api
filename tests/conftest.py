"""
Shared fixtures and test setup for the BillSplit API test suite.

Strategy:
- The app talks to Supabase via the `app.db.supabase` module (plain functions).
- We patch those functions at the service/router level so no real HTTP calls are made.
- The app's `supabase.init()` call at import time requires env vars; we stub them out
  with monkeypatching before the app is created.
- Rate-limit state is reset between tests via a fresh limiter storage override.
"""

import os
import pytest

# Provide dummy env vars BEFORE importing the app so supabase.init() doesn't fail.
os.environ.setdefault("SUPABASE_URL", "http://test.supabase.local")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")

from fastapi.testclient import TestClient

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

    supabase.init() is patched to a no-op so no real network calls occur.
    """
    import unittest.mock as mock
    with mock.patch("app.db.supabase.init"):
        # We also need a minimal _session so verify_token and _request don't
        # crash on None.
        import app.db.supabase as sb
        sb._session = mock.MagicMock()
        sb._base_url = "http://test.supabase.local"
        sb._api_key = "test-service-role-key"

        from main import app as fastapi_app
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

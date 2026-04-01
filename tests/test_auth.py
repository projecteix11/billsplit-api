"""
Tests for authentication middleware and the require_auth dependency.

Coverage:
- AuthMiddleware routes that should be protected: GET /api/orders, PATCH kitchen-status
- require_auth dependency (via endpoints that use it)
- supabase.verify_token behaviour (patched)
"""

import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from tests.conftest import VALID_TOKEN, VALID_USER_ID


def _auth_headers(token: str = VALID_TOKEN) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Protected: GET /api/orders
# ---------------------------------------------------------------------------

class TestAuthOnListOrders:
    def test_no_header_returns_500(self, client: TestClient):
        # TODO: cambiar a 401 cuando se reactive auth_error_handler en main.py
        # (actualmente comentado junto con rate limiting)
        resp = client.get("/api/orders")
        assert resp.status_code == 500

    def test_wrong_scheme_returns_500(self, client: TestClient):
        # TODO: cambiar a 401 cuando se reactive auth_error_handler en main.py
        resp = client.get("/api/orders", headers={"Authorization": "Basic dXNlcjpwYXNz"})
        assert resp.status_code == 500

    def test_bearer_but_empty_token_returns_500(self, client: TestClient):
        # TODO: cambiar a 401 cuando se reactive auth_error_handler en main.py
        with patch("app.middleware.auth.supabase.verify_token", side_effect=ValueError("invalid")):
            resp = client.get("/api/orders", headers={"Authorization": "Bearer "})
        assert resp.status_code == 500

    def test_valid_token_passes_through(self, client: TestClient):
        with patch("app.db.supabase.verify_token", return_value=VALID_USER_ID):
            with patch("app.services.orders.supabase") as mock_sb:
                mock_sb.select.return_value = []
                resp = client.get("/api/orders", headers=_auth_headers())
        assert resp.status_code == 200

    def test_invalid_token_returns_500(self, client: TestClient):
        # TODO: cambiar a 401 cuando se reactive auth_error_handler en main.py
        with patch("app.middleware.auth.supabase.verify_token", side_effect=ValueError("expired")):
            resp = client.get("/api/orders", headers=_auth_headers("bad-token"))
        assert resp.status_code == 500

    def test_missing_header_returns_500(self, client: TestClient):
        # TODO: cambiar a 401 cuando se reactive auth_error_handler en main.py
        resp = client.get("/api/orders")
        assert resp.status_code == 500


# ---------------------------------------------------------------------------
# Protected: PATCH /api/order-items/{id}/kitchen-status
# ---------------------------------------------------------------------------

class TestAuthOnKitchenStatus:
    def test_no_header_returns_500(self, client: TestClient):
        # TODO: cambiar a 401 cuando se reactive auth_error_handler en main.py
        resp = client.patch(
            "/api/order-items/item-1/kitchen-status",
            json={"status": "ready"},
        )
        assert resp.status_code == 500

    def test_invalid_token_returns_500(self, client: TestClient):
        # TODO: cambiar a 401 cuando se reactive auth_error_handler en main.py
        with patch("app.middleware.auth.supabase.verify_token", side_effect=ValueError("bad")):
            resp = client.patch(
                "/api/order-items/item-1/kitchen-status",
                json={"status": "ready"},
                headers=_auth_headers("invalid"),
            )
        assert resp.status_code == 500

    def test_valid_token_allows_update(self, client: TestClient):
        with patch("app.db.supabase.verify_token", return_value=VALID_USER_ID):
            with patch("app.services.orders.supabase") as mock_sb:
                mock_sb.update.return_value = None
                resp = client.patch(
                    "/api/order-items/item-1/kitchen-status",
                    json={"status": "cooking"},
                    headers=_auth_headers(),
                )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Unprotected routes — auth header should NOT be required
# ---------------------------------------------------------------------------

class TestUnprotectedRoutes:
    def test_get_dishes_no_auth_returns_200(self, client: TestClient):
        with patch("app.services.dishes.supabase") as mock_sb:
            mock_sb.select.return_value = []
            resp = client.get("/api/dishes")
        assert resp.status_code == 200

    def test_get_categories_no_auth_returns_200(self, client: TestClient):
        with patch("app.services.dishes.supabase") as mock_sb:
            mock_sb.select.return_value = []
            resp = client.get("/api/categories")
        assert resp.status_code == 200

    def test_get_order_by_id_no_auth_returns_non_401(self, client: TestClient):
        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.select.return_value = []
            resp = client.get("/api/orders/some-order")
        assert resp.status_code != 401

    def test_payment_status_no_auth_returns_200(self, client: TestClient):
        with patch("app.services.orders.supabase") as mock_sb:
            mock_sb.update.return_value = None
            resp = client.patch(
                "/api/order-items/payment-status",
                json={"itemIds": ["i-1"], "status": "paid"},
            )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# require_auth dependency unit tests
# ---------------------------------------------------------------------------

class TestRequireAuthDependency:
    def test_raises_auth_error_with_no_header(self):
        from app.middleware.auth import require_auth, AuthError
        from unittest.mock import MagicMock

        request = MagicMock()
        request.headers = {}
        with pytest.raises(AuthError) as exc_info:
            require_auth(request)
        assert "Missing or invalid" in exc_info.value.message

    def test_raises_auth_error_with_non_bearer_header(self):
        from app.middleware.auth import require_auth, AuthError
        from unittest.mock import MagicMock

        request = MagicMock()
        request.headers = {"Authorization": "Token abc"}
        with pytest.raises(AuthError) as exc_info:
            require_auth(request)
        assert "Missing or invalid" in exc_info.value.message

    def test_raises_auth_error_when_verify_token_fails(self):
        from app.middleware.auth import require_auth, AuthError
        from unittest.mock import MagicMock

        request = MagicMock()
        request.headers = {"Authorization": "Bearer some-token"}
        with patch("app.middleware.auth.supabase.verify_token", side_effect=ValueError("bad")):
            with pytest.raises(AuthError) as exc_info:
                require_auth(request)
        assert "Invalid or expired" in exc_info.value.message

    def test_returns_user_id_on_success(self):
        from app.middleware.auth import require_auth
        from unittest.mock import MagicMock

        request = MagicMock()
        request.headers = {"Authorization": f"Bearer {VALID_TOKEN}"}
        with patch("app.middleware.auth.supabase.verify_token", return_value=VALID_USER_ID):
            user_id = require_auth(request)
        assert user_id == VALID_USER_ID

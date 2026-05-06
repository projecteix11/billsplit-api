"""
Tests for GET /me endpoint.

Coverage:
- Developer users receive avatar_url: null
- Non-developer users with avatar receive avatar_url from users table
- Non-developer users without avatar row receive avatar_url: null
- Non-developer users with null avatar_url in table receive null
- Missing tenant_id returns 400
"""

from unittest.mock import patch

from fastapi.testclient import TestClient

from tests.conftest import VALID_TOKEN, VALID_USER_ID, VALID_TENANT_ID


def _auth_headers(token: str = VALID_TOKEN) -> dict:
    return {"Authorization": f"Bearer {token}"}


class TestMeEndpoint:
    """Test the /me endpoint."""

    def _mock_tenant(self):
        return {
            "id": VALID_TENANT_ID,
            "slug": "test-tenant",
            "plan": "professional",
            "features": {"reservations": True},
            "is_active": True,
            "trial_ends_at": None,
            "max_users": 5,
        }

    def test_developer_returns_avatar_url_null(self, client: TestClient):
        with patch("app.db.supabase.verify_token_full", return_value=(VALID_USER_ID, "", "developer")):
            resp = client.get("/me", headers=_auth_headers())
        data = resp.json()["data"]
        assert data["avatar_url"] is None
        assert data["is_platform_user"] is True

    def test_non_developer_with_avatar_returns_avatar_url(self, client: TestClient):
        tenant = self._mock_tenant()
        with patch("app.db.supabase.verify_token_full", return_value=(VALID_USER_ID, VALID_TENANT_ID, "admin")):
            with patch("app.db.supabase.select") as mock_select:
                mock_select.side_effect = [
                    [tenant],  # tenants query
                    [{"avatar_url": "https://example.com/avatar.jpg"}],  # users query
                ]
                resp = client.get("/me", headers=_auth_headers())
        data = resp.json()["data"]
        assert data["avatar_url"] == "https://example.com/avatar.jpg"
        assert data["is_platform_user"] is False

    def test_non_developer_without_user_row_returns_null(self, client: TestClient):
        tenant = self._mock_tenant()
        with patch("app.db.supabase.verify_token_full", return_value=(VALID_USER_ID, VALID_TENANT_ID, "admin")):
            with patch("app.db.supabase.select") as mock_select:
                mock_select.side_effect = [
                    [tenant],  # tenants query
                    [],  # users query — no row found
                ]
                resp = client.get("/me", headers=_auth_headers())
        data = resp.json()["data"]
        assert data["avatar_url"] is None

    def test_non_developer_with_null_avatar_in_table_returns_null(self, client: TestClient):
        tenant = self._mock_tenant()
        with patch("app.db.supabase.verify_token_full", return_value=(VALID_USER_ID, VALID_TENANT_ID, "admin")):
            with patch("app.db.supabase.select") as mock_select:
                mock_select.side_effect = [
                    [tenant],  # tenants query
                    [{"avatar_url": None}],  # users query — row exists but avatar_url is null
                ]
                resp = client.get("/me", headers=_auth_headers())
        data = resp.json()["data"]
        assert data["avatar_url"] is None

    def test_non_developer_no_tenant_returns_400(self, client: TestClient):
        with patch("app.db.supabase.verify_token_full", return_value=(VALID_USER_ID, "", "admin")):
            resp = client.get("/me", headers=_auth_headers())
        assert resp.status_code == 400
"""
Unit tests for app/db/supabase.py

Tests:
- init() configuration
- verify_token() and verify_token_full() using the supabase-py client

The old _request/select/insert/update helpers no longer exist — they were
replaced by the fluent supabase-py client builder.
"""

import pytest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# init()
# ---------------------------------------------------------------------------

class TestSupabaseInit:
    def test_init_raises_when_url_missing(self, monkeypatch):
        import app.db.supabase as sb
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "some-key")
        with pytest.raises(RuntimeError, match="missing SUPABASE_URL"):
            sb.init()

    def test_init_raises_when_key_missing(self, monkeypatch):
        import app.db.supabase as sb
        monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
        monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
        with pytest.raises(RuntimeError, match="missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY"):
            sb.init()

    def test_init_sets_base_url_and_api_key(self, monkeypatch):
        import app.db.supabase as sb
        monkeypatch.setenv("SUPABASE_URL", "https://myproject.supabase.co")
        monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "my-service-key")
        with patch("app.db.supabase.create_client") as mock_create:
            mock_create.return_value = MagicMock()
            sb.init()
        assert sb._base_url == "https://myproject.supabase.co"
        assert sb._api_key == "my-service-key"

    def test_init_strips_trailing_slash_from_url(self, monkeypatch):
        import app.db.supabase as sb
        monkeypatch.setenv("SUPABASE_URL", "https://myproject.supabase.co/")
        monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "key")
        with patch("app.db.supabase.create_client") as mock_create:
            mock_create.return_value = MagicMock()
            sb.init()
        assert not sb._base_url.endswith("/")

    def test_init_creates_client_via_create_client(self, monkeypatch):
        import app.db.supabase as sb
        monkeypatch.setenv("SUPABASE_URL", "https://myproject.supabase.co")
        monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "my-key")
        with patch("app.db.supabase.create_client") as mock_create:
            fake_client = MagicMock()
            mock_create.return_value = fake_client
            sb.init()
        mock_create.assert_called_once_with("https://myproject.supabase.co", "my-key")
        assert sb._client is fake_client


# ---------------------------------------------------------------------------
# verify_token() and verify_token_full()
# ---------------------------------------------------------------------------

class TestVerifyToken:
    def _make_sb(self):
        import app.db.supabase as sb
        sb._base_url = "http://test.local"
        sb._api_key = "test-key"
        sb._client = MagicMock()
        return sb

    def test_verify_token_returns_user_id_on_success(self):
        sb = self._make_sb()
        mock_user = MagicMock()
        mock_user.id = "user-uuid-abc"
        sb._client.auth.get_user.return_value.user = mock_user

        # verify_token_full needs a tenant lookup too — give it an empty result
        sb._client.table.return_value.select.return_value.eq.return_value.execute.return_value.data = []

        user_id = sb.verify_token("valid-token")
        assert user_id == "user-uuid-abc"

    def test_verify_token_raises_on_auth_exception(self):
        sb = self._make_sb()
        sb._client.auth.get_user.side_effect = Exception("invalid or expired token")
        with pytest.raises(ValueError, match="invalid or expired token"):
            sb.verify_token("bad-token")

    def test_verify_token_raises_when_user_is_none(self):
        sb = self._make_sb()
        sb._client.auth.get_user.return_value.user = None
        with pytest.raises(ValueError):
            sb.verify_token("token-no-user")

    def test_verify_token_full_developer_returns_empty_tenant(self):
        """Developer role: tenant_id is always "" (no DB lookup)."""
        sb = self._make_sb()
        mock_user = MagicMock()
        mock_user.id = "dev-uuid"
        mock_user.user_metadata = {"role": "developer"}
        mock_user.app_metadata = {}
        sb._client.auth.get_user.return_value.user = mock_user

        # Clear cache so the token isn't served from cache
        sb._TOKEN_CACHE.clear()

        user_id, tenant_id, role = sb.verify_token_full("dev-token")
        assert user_id == "dev-uuid"
        assert tenant_id == ""
        assert role == "developer"

    def test_verify_token_full_non_developer_reads_user_roles(self):
        """Non-developer: tenant_id and role come from user_roles table."""
        sb = self._make_sb()
        mock_user = MagicMock()
        mock_user.id = "admin-uuid"
        mock_user.user_metadata = {}
        mock_user.app_metadata = {}
        sb._client.auth.get_user.return_value.user = mock_user

        # Fluent builder for user_roles table
        mock_q = MagicMock()
        mock_q.table.return_value = mock_q
        mock_q.select.return_value = mock_q
        mock_q.eq.return_value = mock_q
        mock_q.limit.return_value = mock_q
        mock_q.execute.return_value.data = [{"tenant_id": "tenant-xyz", "role": "admin"}]
        sb._client = mock_q
        # Re-patch auth on the new mock
        auth_mock = MagicMock()
        auth_user_mock = MagicMock()
        auth_user_mock.id = "admin-uuid"
        auth_user_mock.user_metadata = {}
        auth_user_mock.app_metadata = {}
        auth_mock.get_user.return_value.user = auth_user_mock
        mock_q.auth = auth_mock

        sb._TOKEN_CACHE.clear()

        user_id, tenant_id, role = sb.verify_token_full("admin-token")
        assert user_id == "admin-uuid"
        assert tenant_id == "tenant-xyz"
        assert role == "admin"

    def test_verify_token_full_raises_on_exception(self):
        sb = self._make_sb()
        sb._client.auth.get_user.side_effect = Exception("bad token")
        sb._TOKEN_CACHE.clear()
        with pytest.raises(ValueError):
            sb.verify_token_full("bad-token-unique-99")

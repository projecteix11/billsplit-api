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

def _fluent(data):
    """A MagicMock supabase query builder whose terminal .execute().data is `data`."""
    q = MagicMock()
    q.select.return_value = q
    q.eq.return_value = q
    q.limit.return_value = q
    q.execute.return_value.data = data
    return q


class TestVerifyToken:
    def _make_sb(self, user=None, user_roles=None, platform_admin=False):
        """Build app.db.supabase with a table-name-aware client mock.

        `user` is the object returned by auth.get_user().user. `user_roles` is the
        data returned for the user_roles query; `platform_admin` controls whether the
        platform_admins query returns a membership row.
        """
        import app.db.supabase as sb
        sb._base_url = "http://test.local"
        sb._api_key = "test-key"
        client = MagicMock()
        client.auth.get_user.return_value.user = user

        def table(name):
            if name == "user_roles":
                return _fluent(user_roles or [])
            if name == "platform_admins":
                return _fluent([{"user_id": getattr(user, "id", "")}] if platform_admin else [])
            return _fluent([])

        client.table.side_effect = table
        sb._client = client
        sb._TOKEN_CACHE.clear()
        return sb

    def _user(self, uid, user_metadata=None, app_metadata=None):
        u = MagicMock()
        u.id = uid
        u.user_metadata = user_metadata or {}
        u.app_metadata = app_metadata or {}
        return u

    def test_verify_token_returns_user_id_on_success(self):
        sb = self._make_sb(user=self._user("user-uuid-abc"))
        user_id = sb.verify_token("valid-token")
        assert user_id == "user-uuid-abc"

    def test_verify_token_raises_on_auth_exception(self):
        sb = self._make_sb()
        sb._client.auth.get_user.side_effect = Exception("invalid or expired token")
        with pytest.raises(ValueError, match="invalid or expired token"):
            sb.verify_token("bad-token")

    def test_verify_token_raises_when_user_is_none(self):
        sb = self._make_sb(user=None)
        with pytest.raises(ValueError):
            sb.verify_token("token-no-user")

    def test_verify_token_full_platform_admin_is_developer(self):
        """A platform_admins member resolves to role=developer with no tenant —
        regardless of what user_metadata claims."""
        sb = self._make_sb(
            user=self._user("dev-uuid", user_metadata={"role": "waiter"}),
            platform_admin=True,
        )
        user_id, tenant_id, role = sb.verify_token_full("dev-token")
        assert user_id == "dev-uuid"
        assert tenant_id == ""
        assert role == "developer"

    def test_verify_token_full_staff_reads_user_roles(self):
        """Staff: tenant_id and role come from the user_roles table."""
        sb = self._make_sb(
            user=self._user("admin-uuid"),
            user_roles=[{"tenant_id": "tenant-xyz", "role": "admin"}],
        )
        user_id, tenant_id, role = sb.verify_token_full("admin-token")
        assert user_id == "admin-uuid"
        assert tenant_id == "tenant-xyz"
        assert role == "admin"

    def test_verify_token_full_ignores_self_editable_metadata_role(self):
        """XC-2 escalation guard: a self-registered user who sets
        user_metadata.role=admin + tenant_id=<victim> and has NO user_roles row
        must resolve as an unprivileged 'user' with no tenant — metadata is never
        trusted for authorization."""
        sb = self._make_sb(
            user=self._user(
                "attacker-uuid",
                user_metadata={"role": "admin", "tenant_id": "victim-tenant"},
            ),
            user_roles=[],
            platform_admin=False,
        )
        user_id, tenant_id, role = sb.verify_token_full("attacker-token")
        assert user_id == "attacker-uuid"
        assert tenant_id == ""
        assert role == "user"

    def test_verify_token_full_ignores_self_editable_developer_role(self):
        """A user claiming role=developer in user_metadata but absent from
        platform_admins must NOT be granted the developer role."""
        sb = self._make_sb(
            user=self._user("wannabe-uuid", user_metadata={"role": "developer"}),
            user_roles=[],
            platform_admin=False,
        )
        _, tenant_id, role = sb.verify_token_full("wannabe-token")
        assert tenant_id == ""
        assert role == "user"

    def test_verify_token_full_staff_role_overrides_metadata(self):
        """Even if metadata claims a higher tenant/role, the user_roles row wins."""
        sb = self._make_sb(
            user=self._user(
                "staff-uuid",
                user_metadata={"role": "admin", "tenant_id": "other-tenant"},
            ),
            user_roles=[{"tenant_id": "real-tenant", "role": "waiter"}],
        )
        _, tenant_id, role = sb.verify_token_full("staff-token")
        assert tenant_id == "real-tenant"
        assert role == "waiter"

    def test_verify_token_full_raises_on_exception(self):
        sb = self._make_sb()
        sb._client.auth.get_user.side_effect = Exception("bad token")
        with pytest.raises(ValueError):
            sb.verify_token_full("bad-token-unique-99")

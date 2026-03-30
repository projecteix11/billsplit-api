"""
Unit tests for app/db/supabase.py

Tests the thin HTTP client wrapper:
- init() configuration
- _request() error handling
- select(), insert(), update() helper methods
- verify_token()

All actual HTTP calls are intercepted via unittest.mock.
"""

import pytest
from unittest.mock import patch, MagicMock, PropertyMock
import requests


# ---------------------------------------------------------------------------
# Helpers to get a freshly patched supabase module state
# ---------------------------------------------------------------------------

def _make_response(status_code: int, json_data=None, text: str = "") -> MagicMock:
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status_code
    resp.text = text if json_data is None else ""
    resp.content = b"content" if json_data else b""
    if json_data is not None:
        resp.json.return_value = json_data
        resp.text = str(json_data)
        resp.content = b"content"
    else:
        resp.json.side_effect = Exception("no json")
    return resp


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
        with patch("requests.Session") as MockSession:
            instance = MagicMock()
            MockSession.return_value = instance
            sb.init()
        assert sb._base_url == "https://myproject.supabase.co"
        assert sb._api_key == "my-service-key"

    def test_init_strips_trailing_slash_from_url(self, monkeypatch):
        import app.db.supabase as sb
        monkeypatch.setenv("SUPABASE_URL", "https://myproject.supabase.co/")
        monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "key")
        with patch("requests.Session") as MockSession:
            MockSession.return_value = MagicMock()
            sb.init()
        assert not sb._base_url.endswith("/")


# ---------------------------------------------------------------------------
# _request()
# ---------------------------------------------------------------------------

class TestRequestHelper:
    def _make_sb(self):
        import app.db.supabase as sb
        sb._base_url = "http://test.local"
        sb._api_key = "test-key"
        sb._session = MagicMock()
        return sb

    def test_request_raises_on_4xx_status(self):
        sb = self._make_sb()
        resp = _make_response(404, {"message": "not found"})
        sb._session.request.return_value = resp
        with pytest.raises(RuntimeError, match="supabase 404"):
            sb._request("GET", "orders", query="id=eq.x")

    def test_request_raises_on_5xx_status(self):
        sb = self._make_sb()
        resp = _make_response(500, {"message": "internal error"})
        sb._session.request.return_value = resp
        with pytest.raises(RuntimeError, match="supabase 500"):
            sb._request("GET", "orders")

    def test_request_raises_uses_text_when_json_fails(self):
        sb = self._make_sb()
        resp = MagicMock()
        resp.status_code = 503
        resp.text = "Service Unavailable"
        resp.json.side_effect = Exception("not json")
        sb._session.request.return_value = resp
        with pytest.raises(RuntimeError, match="Service Unavailable"):
            sb._request("GET", "orders")

    def test_request_returns_json_when_result_type_set(self):
        sb = self._make_sb()
        data = [{"id": "1", "name": "test"}]
        resp = _make_response(200, data)
        sb._session.request.return_value = resp
        result = sb._request("GET", "orders", result_type=True)
        assert result == data

    def test_request_returns_none_when_no_result_type(self):
        sb = self._make_sb()
        resp = _make_response(200, [{"id": "1"}])
        sb._session.request.return_value = resp
        result = sb._request("PATCH", "orders", query="id=eq.1", body={"status": "closed"})
        assert result is None

    def test_request_returns_none_for_null_body(self):
        sb = self._make_sb()
        resp = MagicMock()
        resp.status_code = 200
        resp.content = b"null"
        resp.text = "null"
        resp.json.return_value = None
        sb._session.request.return_value = resp
        result = sb._request("GET", "orders", result_type=True)
        assert result is None

    def test_request_includes_prefer_header_when_set(self):
        sb = self._make_sb()
        resp = _make_response(200, [])
        sb._session.request.return_value = resp
        sb._request("POST", "orders", prefer="return=representation", result_type=True)
        call_kwargs = sb._session.request.call_args
        assert call_kwargs[1]["headers"]["Prefer"] == "return=representation"

    def test_request_constructs_correct_url_with_query(self):
        sb = self._make_sb()
        resp = _make_response(200, [])
        sb._session.request.return_value = resp
        sb._request("GET", "dishes", query="is_available=eq.true")
        call_args = sb._session.request.call_args
        url = call_args[0][1]
        assert url == "http://test.local/rest/v1/dishes?is_available=eq.true"


# ---------------------------------------------------------------------------
# select(), insert(), update()
# ---------------------------------------------------------------------------

class TestSelectInsertUpdate:
    def _make_sb(self):
        import app.db.supabase as sb
        sb._base_url = "http://test.local"
        sb._api_key = "test-key"
        sb._session = MagicMock()
        return sb

    def test_select_returns_list(self):
        sb = self._make_sb()
        data = [{"id": "1"}]
        resp = _make_response(200, data)
        sb._session.request.return_value = resp
        result = sb.select("orders", "status=eq.open")
        assert result == data

    def test_select_returns_empty_list_on_null_response(self):
        sb = self._make_sb()
        resp = MagicMock()
        resp.status_code = 200
        resp.content = b""
        resp.text = "null"
        resp.json.return_value = None
        sb._session.request.return_value = resp
        result = sb.select("orders")
        assert result == []

    def test_insert_with_return_result_uses_prefer_header(self):
        sb = self._make_sb()
        data = [{"id": "new-id"}]
        resp = _make_response(201, data)
        sb._session.request.return_value = resp
        sb.insert("orders", {"status": "open"}, return_result=True)
        call_kwargs = sb._session.request.call_args[1]
        assert call_kwargs["headers"]["Prefer"] == "return=representation"

    def test_insert_without_return_result_has_no_prefer_header(self):
        sb = self._make_sb()
        resp = _make_response(201, None)
        resp.status_code = 201
        resp.content = b""
        resp.text = ""
        resp.json.side_effect = Exception()
        sb._session.request.return_value = resp
        sb.insert("order_items", [{"dish_name": "X"}], return_result=False)
        call_kwargs = sb._session.request.call_args[1]
        assert call_kwargs["headers"].get("Prefer", "") == ""

    def test_update_sends_patch_request(self):
        sb = self._make_sb()
        resp = MagicMock()
        resp.status_code = 200
        resp.content = b""
        resp.text = ""
        resp.json.side_effect = Exception()
        sb._session.request.return_value = resp
        sb.update("orders", "id=eq.1", {"status": "closed"})
        method = sb._session.request.call_args[0][0]
        assert method == "PATCH"


# ---------------------------------------------------------------------------
# verify_token()
# ---------------------------------------------------------------------------

class TestVerifyToken:
    def _make_sb(self):
        import app.db.supabase as sb
        sb._base_url = "http://test.local"
        sb._api_key = "test-key"
        sb._session = MagicMock()
        return sb

    def test_verify_token_returns_user_id_on_success(self):
        sb = self._make_sb()
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"id": "user-uuid-abc", "email": "test@example.com"}
        sb._session.get.return_value = resp
        user_id = sb.verify_token("valid-token")
        assert user_id == "user-uuid-abc"

    def test_verify_token_raises_on_non_200(self):
        sb = self._make_sb()
        resp = MagicMock()
        resp.status_code = 401
        sb._session.get.return_value = resp
        with pytest.raises(ValueError, match="invalid or expired token"):
            sb.verify_token("bad-token")

    def test_verify_token_raises_when_no_user_id_in_response(self):
        sb = self._make_sb()
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"email": "test@example.com"}  # no "id"
        sb._session.get.return_value = resp
        with pytest.raises(ValueError, match="no user id"):
            sb.verify_token("token-without-id")

    def test_verify_token_sends_correct_auth_header(self):
        sb = self._make_sb()
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"id": "user-1"}
        sb._session.get.return_value = resp
        sb.verify_token("my-bearer-token")
        call_kwargs = sb._session.get.call_args[1]
        assert call_kwargs["headers"]["Authorization"] == "Bearer my-bearer-token"

    def test_verify_token_calls_auth_endpoint(self):
        sb = self._make_sb()
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {"id": "user-1"}
        sb._session.get.return_value = resp
        sb.verify_token("token")
        url = sb._session.get.call_args[0][0]
        assert "/auth/v1/user" in url

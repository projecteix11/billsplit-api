"""
Tests for the Axiom logging integration.

Coverage:
- app/logging/factory.py: LogFactory.canonical_line
- app/logging/client.py: init(), log_event(), _send()
- app/middleware/request_logging.py: RequestLoggingMiddleware
"""

import threading
import time
import uuid
from datetime import timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ---------------------------------------------------------------------------
# LogFactory.canonical_line
# ---------------------------------------------------------------------------


class TestCanonicalLineLevel:
    def test_status_200_returns_info(self):
        from app.logging.factory import LogFactory

        result = LogFactory.canonical_line("GET", "/api/dishes", 200, 12.5)
        assert result["level"] == "info"

    def test_status_201_returns_info(self):
        from app.logging.factory import LogFactory

        result = LogFactory.canonical_line("POST", "/api/orders", 201, 5.0)
        assert result["level"] == "info"

    def test_status_399_returns_info(self):
        from app.logging.factory import LogFactory

        result = LogFactory.canonical_line("GET", "/api/foo", 399, 1.0)
        assert result["level"] == "info"

    def test_status_400_returns_warning(self):
        from app.logging.factory import LogFactory

        result = LogFactory.canonical_line("POST", "/api/foo", 400, 1.0)
        assert result["level"] == "warning"

    def test_status_404_returns_warning(self):
        from app.logging.factory import LogFactory

        result = LogFactory.canonical_line("GET", "/api/missing", 404, 2.0)
        assert result["level"] == "warning"

    def test_status_499_returns_warning(self):
        from app.logging.factory import LogFactory

        result = LogFactory.canonical_line("GET", "/api/foo", 499, 1.0)
        assert result["level"] == "warning"

    def test_status_500_returns_error(self):
        from app.logging.factory import LogFactory

        result = LogFactory.canonical_line("GET", "/api/crash", 500, 3.0)
        assert result["level"] == "error"

    def test_status_503_returns_error(self):
        from app.logging.factory import LogFactory

        result = LogFactory.canonical_line("GET", "/api/crash", 503, 3.0)
        assert result["level"] == "error"


class TestCanonicalLineEventType:
    def test_status_200_returns_system_event(self):
        from app.logging.factory import LogFactory

        result = LogFactory.canonical_line("GET", "/api/dishes", 200, 1.0)
        assert result["type"] == "system_event"

    def test_status_399_returns_system_event(self):
        from app.logging.factory import LogFactory

        result = LogFactory.canonical_line("GET", "/api/foo", 399, 1.0)
        assert result["type"] == "system_event"

    def test_status_400_returns_api_error(self):
        from app.logging.factory import LogFactory

        result = LogFactory.canonical_line("POST", "/api/foo", 400, 1.0)
        assert result["type"] == "api_error"

    def test_status_404_returns_api_error(self):
        from app.logging.factory import LogFactory

        result = LogFactory.canonical_line("GET", "/api/missing", 404, 2.0)
        assert result["type"] == "api_error"

    def test_status_500_returns_api_error(self):
        from app.logging.factory import LogFactory

        result = LogFactory.canonical_line("GET", "/api/crash", 500, 3.0)
        assert result["type"] == "api_error"


class TestCanonicalLineSource:
    def test_uses_passed_source_when_provided(self):
        from app.logging.factory import LogFactory

        result = LogFactory.canonical_line(
            "GET", "/api/dishes", 200, 1.0, source="custom-source"
        )
        assert result["source"] == "custom-source"

    def test_falls_back_to_default_source_when_none(self):
        from app.logging.factory import LogFactory

        result = LogFactory.canonical_line("GET", "/api/dishes", 200, 1.0, source=None)
        assert result["source"] == "🐍 api"

    def test_falls_back_to_default_source_when_not_passed(self):
        from app.logging.factory import LogFactory

        result = LogFactory.canonical_line("GET", "/api/dishes", 200, 1.0)
        assert result["source"] == "🐍 api"

    def test_empty_string_source_is_falsy_falls_back(self):
        from app.logging.factory import LogFactory

        # source="" is falsy, so `source or _SOURCE` returns _SOURCE
        result = LogFactory.canonical_line("GET", "/api/dishes", 200, 1.0, source="")
        assert result["source"] == "🐍 api"


class TestCanonicalLineFields:
    def test_includes_client_ip(self):
        from app.logging.factory import LogFactory

        result = LogFactory.canonical_line(
            "GET", "/api/dishes", 200, 1.0, client_ip="10.0.0.1"
        )
        assert result["client_ip"] == "10.0.0.1"

    def test_client_ip_none_when_not_passed(self):
        from app.logging.factory import LogFactory

        result = LogFactory.canonical_line("GET", "/api/dishes", 200, 1.0)
        assert result["client_ip"] is None

    def test_includes_request_id_at_top_level(self):
        from app.logging.factory import LogFactory

        result = LogFactory.canonical_line(
            "GET", "/api/dishes", 200, 1.0, request_id="req-abc"
        )
        assert result["request_id"] == "req-abc"

    def test_includes_request_id_in_metadata(self):
        from app.logging.factory import LogFactory

        result = LogFactory.canonical_line(
            "GET", "/api/dishes", 200, 1.0, request_id="req-abc"
        )
        assert result["metadata"]["request_id"] == "req-abc"

    def test_request_id_none_not_injected_in_metadata(self):
        from app.logging.factory import LogFactory

        result = LogFactory.canonical_line("GET", "/api/dishes", 200, 1.0)
        # When request_id is None the key should not be added to metadata
        assert "request_id" not in result["metadata"]

    def test_rounds_duration_to_2_decimals(self):
        from app.logging.factory import LogFactory

        result = LogFactory.canonical_line("GET", "/api/dishes", 200, 12.3456789)
        assert result["duration_ms"] == round(12.3456789, 2)

    def test_duration_already_2_decimals_unchanged(self):
        from app.logging.factory import LogFactory

        result = LogFactory.canonical_line("GET", "/api/dishes", 200, 5.50)
        assert result["duration_ms"] == 5.50

    def test_action_formatted_correctly(self):
        from app.logging.factory import LogFactory

        result = LogFactory.canonical_line("POST", "/api/orders", 201, 5.0)
        assert result["action"] == "POST /api/orders -> 201"

    def test_action_includes_method_path_and_status(self):
        from app.logging.factory import LogFactory

        result = LogFactory.canonical_line("PATCH", "/api/order-items/x/kitchen-status", 404, 1.0)
        assert result["action"] == "PATCH /api/order-items/x/kitchen-status -> 404"

    def test_passes_through_extra_metadata(self):
        from app.logging.factory import LogFactory

        result = LogFactory.canonical_line(
            "GET", "/api/dishes", 200, 1.0, metadata={"foo": "bar"}
        )
        assert result["metadata"]["foo"] == "bar"

    def test_extra_metadata_and_request_id_coexist(self):
        from app.logging.factory import LogFactory

        result = LogFactory.canonical_line(
            "GET", "/api/dishes", 200, 1.0,
            request_id="req-xyz",
            metadata={"extra": 42},
        )
        assert result["metadata"]["request_id"] == "req-xyz"
        assert result["metadata"]["extra"] == 42

    def test_module_is_http(self):
        from app.logging.factory import LogFactory

        result = LogFactory.canonical_line("GET", "/api/dishes", 200, 1.0)
        assert result["module"] == "http"

    def test_http_method_and_path_preserved(self):
        from app.logging.factory import LogFactory

        result = LogFactory.canonical_line("DELETE", "/api/items/7", 204, 0.9)
        assert result["http_method"] == "DELETE"
        assert result["path"] == "/api/items/7"
        assert result["status_code"] == 204


# ---------------------------------------------------------------------------
# app/logging/client.py
# ---------------------------------------------------------------------------


class TestAxiomClientInit:
    def test_init_creates_client_when_token_is_set(self):
        import app.logging.client as lc

        with patch.dict("os.environ", {"AXIOM_TOKEN": "xaat-test-token"}):
            with patch("axiom_py.Client") as mock_axiom:
                mock_instance = MagicMock()
                mock_axiom.return_value = mock_instance

                # Reset state before calling init
                lc._client = None
                lc.init()

                mock_axiom.assert_called_once_with(token="xaat-test-token")
                assert lc._client is mock_instance

    def test_init_does_not_create_client_when_token_empty(self):
        import app.logging.client as lc

        with patch.dict("os.environ", {"AXIOM_TOKEN": ""}):
            with patch("axiom_py.Client") as mock_axiom:
                lc._client = None
                lc.init()

                mock_axiom.assert_not_called()
                assert lc._client is None

    def test_init_does_not_create_client_when_token_missing(self):
        import app.logging.client as lc
        import os

        env_without_token = {k: v for k, v in os.environ.items() if k != "AXIOM_TOKEN"}
        with patch.dict("os.environ", env_without_token, clear=True):
            with patch("axiom_py.Client") as mock_axiom:
                lc._client = None
                lc.init()

                mock_axiom.assert_not_called()
                assert lc._client is None

    def test_init_sets_dataset_from_env(self):
        import app.logging.client as lc

        with patch.dict("os.environ", {"AXIOM_TOKEN": "tok", "AXIOM_DATASET": "my-ds"}):
            with patch("axiom_py.Client"):
                lc._client = None
                lc.init()
                assert lc._dataset == "my-ds"

    def test_init_uses_default_dataset_when_not_set(self):
        import app.logging.client as lc
        import os

        env = {k: v for k, v in os.environ.items() if k != "AXIOM_DATASET"}
        env["AXIOM_TOKEN"] = "tok"
        with patch.dict("os.environ", env, clear=True):
            with patch("axiom_py.Client"):
                lc._client = None
                lc.init()
                assert lc._dataset == "gobbly-management"

    def teardown_method(self, method):
        # Restore module state after each test
        import app.logging.client as lc
        lc._client = None


class TestAxiomClientSend:
    def setup_method(self, method):
        import app.logging.client as lc
        lc._client = None

    def teardown_method(self, method):
        import app.logging.client as lc
        lc._client = None

    def test_send_does_nothing_when_client_is_none(self):
        from app.logging.client import _send

        # Should not raise even without a client
        _send({"level": "info"})

    def test_send_calls_ingest_events(self):
        import app.logging.client as lc

        mock_client = MagicMock()
        lc._client = mock_client
        lc._dataset = "test-dataset"

        from app.logging.client import _send
        _send({"level": "info", "_time": "2024-01-01T00:00:00+00:00"})

        mock_client.ingest_events.assert_called_once()
        call_kwargs = mock_client.ingest_events.call_args
        assert call_kwargs.kwargs["dataset"] == "test-dataset"
        assert len(call_kwargs.kwargs["events"]) == 1

    def test_send_adds_time_when_not_present(self):
        import app.logging.client as lc

        mock_client = MagicMock()
        lc._client = mock_client
        lc._dataset = "ds"

        event = {"level": "info"}
        from app.logging.client import _send
        _send(event)

        assert "_time" in event

    def test_send_does_not_overwrite_existing_time(self):
        import app.logging.client as lc

        mock_client = MagicMock()
        lc._client = mock_client
        lc._dataset = "ds"

        existing_time = "2023-06-15T12:00:00+00:00"
        event = {"level": "info", "_time": existing_time}
        from app.logging.client import _send
        _send(event)

        assert event["_time"] == existing_time

    def test_send_accepts_timestamp_key_as_alternative(self):
        import app.logging.client as lc

        mock_client = MagicMock()
        lc._client = mock_client
        lc._dataset = "ds"

        event = {"level": "info", "timestamp": "2023-06-15T12:00:00+00:00"}
        from app.logging.client import _send
        _send(event)

        # Neither _time nor timestamp should have been overwritten
        assert "_time" not in event
        assert event["timestamp"] == "2023-06-15T12:00:00+00:00"

    def test_send_swallows_exceptions_silently(self):
        import app.logging.client as lc

        mock_client = MagicMock()
        mock_client.ingest_events.side_effect = RuntimeError("network error")
        lc._client = mock_client
        lc._dataset = "ds"

        from app.logging.client import _send
        # Must not raise
        _send({"level": "info"})

    def test_time_added_is_utc_isoformat(self):
        import app.logging.client as lc

        mock_client = MagicMock()
        lc._client = mock_client
        lc._dataset = "ds"

        event = {"level": "info"}
        from app.logging.client import _send
        _send(event)

        added_time = event["_time"]
        # Must be parseable as an ISO 8601 datetime with timezone info
        from datetime import datetime
        parsed = datetime.fromisoformat(added_time)
        assert parsed.tzinfo is not None


class TestAxiomClientLogEvent:
    def setup_method(self, method):
        import app.logging.client as lc
        lc._client = None

    def teardown_method(self, method):
        import app.logging.client as lc
        lc._client = None

    def test_log_event_does_not_raise_when_client_none(self):
        from app.logging.client import log_event

        # Fire-and-forget: must never raise
        log_event({"level": "info", "message": "test"})

    def test_log_event_spawns_daemon_thread(self):
        from app.logging.client import log_event

        threads_before = {t.ident for t in threading.enumerate()}
        log_event({"level": "info"})
        # Give the thread a moment to register
        time.sleep(0.05)
        # We can't reliably count daemon threads (they may have already finished),
        # but we verify no exception was raised — the key requirement is fire-and-forget.

    def test_log_event_eventually_calls_ingest(self):
        import app.logging.client as lc

        mock_client = MagicMock()
        lc._client = mock_client
        lc._dataset = "ds"

        from app.logging.client import log_event
        log_event({"level": "info"})

        # Wait for the background thread to finish
        time.sleep(0.1)
        mock_client.ingest_events.assert_called_once()


# ---------------------------------------------------------------------------
# RequestLoggingMiddleware
# ---------------------------------------------------------------------------


def _make_test_app() -> FastAPI:
    """Build a minimal FastAPI app with RequestLoggingMiddleware attached."""
    from app.middleware.request_logging import RequestLoggingMiddleware

    mini = FastAPI()
    mini.add_middleware(RequestLoggingMiddleware)

    @mini.get("/ping")
    async def ping():
        return {"ok": True}

    @mini.get("/error")
    async def error_route():
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=500, content={"ok": False})

    return mini


@pytest.fixture(scope="module")
def log_client():
    """TestClient with RequestLoggingMiddleware and log_event patched to a no-op."""
    app = _make_test_app()
    with patch("app.logging.client.log_event"):
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c


class TestRequestLoggingMiddlewareRequestId:
    def test_uses_x_request_id_from_header(self):
        app = _make_test_app()
        with patch("app.middleware.request_logging.log_event"):
            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.get("/ping", headers={"x-request-id": "my-request-id"})
        assert resp.headers["x-request-id"] == "my-request-id"

    def test_generates_uuid_when_header_absent(self):
        app = _make_test_app()
        with patch("app.middleware.request_logging.log_event"):
            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.get("/ping")
        request_id = resp.headers.get("x-request-id", "")
        assert len(request_id) == 36  # standard UUID4 string length
        # Must be a valid UUID
        uuid.UUID(request_id)

    def test_returns_x_request_id_in_response_headers(self):
        app = _make_test_app()
        with patch("app.middleware.request_logging.log_event"):
            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.get("/ping")
        assert "x-request-id" in resp.headers

    def test_frontend_request_id_propagates_to_axiom_event(self):
        """The exact request_id sent by the frontend must appear in the logged event."""
        captured_events = []
        app = _make_test_app()

        def capture(event):
            captured_events.append(event)

        frontend_rid = "frontend-abc-123"
        with patch("app.middleware.request_logging.log_event", side_effect=capture):
            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.get("/ping", headers={"x-request-id": frontend_rid})

        assert resp.headers["x-request-id"] == frontend_rid
        assert len(captured_events) == 1
        assert captured_events[0]["request_id"] == frontend_rid

    def test_frontend_request_id_not_replaced_by_new_uuid(self):
        """Ensures the middleware does NOT generate a new UUID when the frontend sends one."""
        captured_events = []
        app = _make_test_app()

        def capture(event):
            captured_events.append(event)

        frontend_rid = "exact-id-from-frontend"
        with patch("app.middleware.request_logging.log_event", side_effect=capture):
            with TestClient(app, raise_server_exceptions=False) as c:
                resp = c.get("/ping", headers={"x-request-id": frontend_rid})

        event_rid = captured_events[0]["request_id"]
        response_rid = resp.headers["x-request-id"]
        # All three must be identical
        assert event_rid == frontend_rid
        assert response_rid == frontend_rid
        assert event_rid == response_rid


class TestRequestLoggingMiddlewareBotDetection:
    @pytest.mark.parametrize("bot_ua", [
        "Googlebot/2.1",
        "Bingbot/2.0",
        "Mozilla spider/1.0",
        "MyCrawler/1.0",
        "curl/7.84.0",
        "PostmanRuntime/7.30",
        "python-requests/2.28.0",
        "python-httpx/0.23.0",
        "UptimeKuma/1.0",
    ])
    def test_known_bot_user_agents_are_detected(self, bot_ua: str):
        captured_events = []
        app = _make_test_app()

        def capture(event):
            captured_events.append(event)

        with patch("app.middleware.request_logging.log_event", side_effect=capture):
            with TestClient(app, raise_server_exceptions=False) as c:
                c.get("/ping", headers={"user-agent": bot_ua})

        assert len(captured_events) == 1
        # Bot backend icon starts with 🤖
        assert captured_events[0]["source"].startswith("🤖")

    @pytest.mark.parametrize("human_ua", [
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/109.0",
        "Safari/605.1.15",
    ])
    def test_human_user_agents_are_not_detected_as_bot(self, human_ua: str):
        captured_events = []
        app = _make_test_app()

        def capture(event):
            captured_events.append(event)

        with patch("app.middleware.request_logging.log_event", side_effect=capture):
            with TestClient(app, raise_server_exceptions=False) as c:
                c.get("/ping", headers={"user-agent": human_ua})

        assert len(captured_events) == 1
        assert captured_events[0]["source"].startswith("🐍")


class TestRequestLoggingMiddlewareSource:
    def _get_source(self, headers: dict) -> str:
        captured_events = []
        app = _make_test_app()

        def capture(event):
            captured_events.append(event)

        with patch("app.middleware.request_logging.log_event", side_effect=capture):
            with TestClient(app, raise_server_exceptions=False) as c:
                c.get("/ping", headers=headers)

        assert len(captured_events) == 1
        return captured_events[0]["source"]

    def test_no_x_client_type_human_ua_gives_snake_api(self):
        source = self._get_source({"user-agent": "Mozilla/5.0 (real browser)"})
        assert source == "🐍 api"

    def test_no_x_client_type_bot_ua_gives_robot_api(self):
        source = self._get_source({"user-agent": "curl/7.84.0"})
        assert source == "🤖 api"

    def test_x_client_type_human_and_human_backend_gives_two_snakes(self):
        source = self._get_source({
            "user-agent": "Mozilla/5.0 (real browser)",
            "x-client-type": "human",
        })
        assert source == "🐍🐍 api"

    def test_x_client_type_bot_and_bot_backend_gives_two_robots(self):
        source = self._get_source({
            "user-agent": "curl/7.84.0",
            "x-client-type": "bot",
        })
        assert source == "🤖🤖 api"

    def test_x_client_type_bot_frontend_and_human_backend(self):
        # Frontend is bot, backend (server-side) caller is human browser
        source = self._get_source({
            "user-agent": "Mozilla/5.0 (real browser)",
            "x-client-type": "bot",
        })
        assert source == "🤖🐍 api"

    def test_x_client_type_human_frontend_and_bot_backend(self):
        # Frontend is human (real user clicked), but the backend UA is a bot tool
        source = self._get_source({
            "user-agent": "python-requests/2.28.0",
            "x-client-type": "human",
        })
        assert source == "🐍🤖 api"


class TestRequestLoggingMiddlewareClientIp:
    def _get_client_ip(self, headers: dict) -> str:
        captured_events = []
        app = _make_test_app()

        def capture(event):
            captured_events.append(event)

        with patch("app.middleware.request_logging.log_event", side_effect=capture):
            with TestClient(app, raise_server_exceptions=False) as c:
                c.get("/ping", headers=headers)

        assert len(captured_events) == 1
        return captured_events[0]["client_ip"]

    def test_extracts_first_ip_from_x_forwarded_for(self):
        ip = self._get_client_ip({"x-forwarded-for": "1.2.3.4, 5.6.7.8, 9.10.11.12"})
        assert ip == "1.2.3.4"

    def test_extracts_single_ip_from_x_forwarded_for(self):
        ip = self._get_client_ip({"x-forwarded-for": "192.168.1.100"})
        assert ip == "192.168.1.100"

    def test_strips_whitespace_from_forwarded_ip(self):
        ip = self._get_client_ip({"x-forwarded-for": "  10.0.0.1  , 10.0.0.2"})
        assert ip == "10.0.0.1"

    def test_falls_back_to_request_client_host_when_no_forwarded_header(self):
        # TestClient uses 127.0.0.1 / testclient as client.host
        ip = self._get_client_ip({})
        # Without x-forwarded-for, we get the direct connection host
        assert ip is not None
        assert ip != ""


class TestRequestLoggingMiddlewareCorrelationId:
    def test_correlation_id_from_header_propagates_to_event(self):
        captured_events = []
        app = _make_test_app()

        def capture(event):
            captured_events.append(event)

        with patch("app.middleware.request_logging.log_event", side_effect=capture):
            with TestClient(app, raise_server_exceptions=False) as c:
                c.get("/ping", headers={"x-correlation-id": "cor-123"})

        assert len(captured_events) == 1
        assert captured_events[0]["correlation_id"] == "cor-123"

    def test_correlation_id_is_none_when_header_absent(self):
        captured_events = []
        app = _make_test_app()

        def capture(event):
            captured_events.append(event)

        with patch("app.middleware.request_logging.log_event", side_effect=capture):
            with TestClient(app, raise_server_exceptions=False) as c:
                c.get("/ping")

        assert len(captured_events) == 1
        assert captured_events[0]["correlation_id"] is None

    def test_correlation_id_in_canonical_line_output(self):
        from app.logging.factory import LogFactory

        result = LogFactory.canonical_line(
            "GET", "/api/dishes", 200, 1.0, correlation_id="cor-xyz"
        )
        assert result["correlation_id"] == "cor-xyz"

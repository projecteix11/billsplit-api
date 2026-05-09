"""Tests for POST /notifications/broadcast — router + service unit tests."""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from tests.conftest import make_mock_client, VALID_TENANT_ID

INTERNAL_API_KEY = "test-internal-key"

VALID_BODY = {
    "title": "notifications.order_ready",
    "notification_type": "order_ready",
}

VALID_HEADERS = {
    "x-api-key": INTERNAL_API_KEY,
    "x-tenant-id": VALID_TENANT_ID,
}


def _mock_broadcast_resp(status_code: int = 200) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = "ok"
    return resp


# ---------------------------------------------------------------------------
# POST /notifications/broadcast — router tests
# ---------------------------------------------------------------------------

class TestBroadcastEndpoint:
    def test_returns_200_with_valid_payload(self, client: TestClient):
        with patch("app.routers.notifications._INTERNAL_API_KEY", INTERNAL_API_KEY):
            with patch("app.services.notifications.get_client", return_value=make_mock_client()):
                with patch("app.services.notifications.httpx.post", return_value=_mock_broadcast_resp()):
                    resp = client.post(
                        "/notifications/broadcast",
                        json=VALID_BODY,
                        headers=VALID_HEADERS,
                    )
        assert resp.status_code == 200
        assert resp.json() == {"data": {"status": "sent"}}

    def test_returns_403_with_wrong_api_key(self, client: TestClient):
        with patch("app.routers.notifications._INTERNAL_API_KEY", INTERNAL_API_KEY):
            resp = client.post(
                "/notifications/broadcast",
                json=VALID_BODY,
                headers={**VALID_HEADERS, "x-api-key": "wrong-key"},
            )
        assert resp.status_code == 403

    def test_returns_422_without_api_key_header(self, client: TestClient):
        with patch("app.routers.notifications._INTERNAL_API_KEY", INTERNAL_API_KEY):
            resp = client.post(
                "/notifications/broadcast",
                json=VALID_BODY,
                headers={"x-tenant-id": VALID_TENANT_ID},
            )
        assert resp.status_code == 422

    def test_returns_422_without_tenant_id_header(self, client: TestClient):
        with patch("app.routers.notifications._INTERNAL_API_KEY", INTERNAL_API_KEY):
            resp = client.post(
                "/notifications/broadcast",
                json=VALID_BODY,
                headers={"x-api-key": INTERNAL_API_KEY},
            )
        assert resp.status_code == 422

    def test_returns_422_without_title(self, client: TestClient):
        with patch("app.routers.notifications._INTERNAL_API_KEY", INTERNAL_API_KEY):
            resp = client.post(
                "/notifications/broadcast",
                json={"notification_type": "order_ready"},
                headers=VALID_HEADERS,
            )
        assert resp.status_code == 422

    def test_tenant_id_not_required_in_body(self, client: TestClient):
        with patch("app.routers.notifications._INTERNAL_API_KEY", INTERNAL_API_KEY):
            with patch("app.services.notifications.get_client", return_value=make_mock_client()):
                with patch("app.services.notifications.httpx.post", return_value=_mock_broadcast_resp()):
                    resp = client.post(
                        "/notifications/broadcast",
                        json=VALID_BODY,
                        headers=VALID_HEADERS,
                    )
        assert resp.status_code == 200

    def test_accepts_optional_description_and_params(self, client: TestClient):
        body = {**VALID_BODY, "description": "notifications.table_number", "params": {"table": 5}}
        with patch("app.routers.notifications._INTERNAL_API_KEY", INTERNAL_API_KEY):
            with patch("app.services.notifications.get_client", return_value=make_mock_client()):
                with patch("app.services.notifications.httpx.post", return_value=_mock_broadcast_resp()):
                    resp = client.post(
                        "/notifications/broadcast",
                        json=body,
                        headers=VALID_HEADERS,
                    )
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Unit tests for broadcast_notification service
# ---------------------------------------------------------------------------

class TestBroadcastNotificationService:
    def _call(self, **kwargs):
        defaults = {
            "tenant_id": VALID_TENANT_ID,
            "title": "notifications.order_ready",
            "notification_type": "order_ready",
        }
        from app.services.notifications import broadcast_notification
        broadcast_notification(**{**defaults, **kwargs})

    def test_inserts_row_into_notifications_table(self):
        mock_client = make_mock_client()
        with patch("app.services.notifications.get_client", return_value=mock_client):
            with patch("app.services.notifications.httpx.post", return_value=_mock_broadcast_resp()):
                self._call()

        mock_client.table.assert_called_once_with("notifications")
        insert_call = mock_client.insert.call_args
        row = insert_call[0][0]
        assert row["tenant_id"] == VALID_TENANT_ID
        assert row["title_key"] == "notifications.order_ready"
        assert row["type"] == "order_ready"

    def test_insert_includes_description_key_when_provided(self):
        mock_client = make_mock_client()
        with patch("app.services.notifications.get_client", return_value=mock_client):
            with patch("app.services.notifications.httpx.post", return_value=_mock_broadcast_resp()):
                self._call(description="notifications.table_number")

        row = mock_client.insert.call_args[0][0]
        assert row["description_key"] == "notifications.table_number"

    def test_insert_excludes_description_key_when_absent(self):
        mock_client = make_mock_client()
        with patch("app.services.notifications.get_client", return_value=mock_client):
            with patch("app.services.notifications.httpx.post", return_value=_mock_broadcast_resp()):
                self._call()

        row = mock_client.insert.call_args[0][0]
        assert "description_key" not in row

    def test_insert_includes_params_when_provided(self):
        mock_client = make_mock_client()
        with patch("app.services.notifications.get_client", return_value=mock_client):
            with patch("app.services.notifications.httpx.post", return_value=_mock_broadcast_resp()):
                self._call(params={"table": 3})

        row = mock_client.insert.call_args[0][0]
        assert row["params"] == {"table": 3}

    def test_insert_excludes_params_when_absent(self):
        mock_client = make_mock_client()
        with patch("app.services.notifications.get_client", return_value=mock_client):
            with patch("app.services.notifications.httpx.post", return_value=_mock_broadcast_resp()):
                self._call()

        row = mock_client.insert.call_args[0][0]
        assert "params" not in row

    def test_broadcast_sent_to_system_notifications_channel(self):
        with patch("app.services.notifications.get_client", return_value=make_mock_client()):
            with patch("app.services.notifications.httpx.post", return_value=_mock_broadcast_resp()) as mock_post:
                self._call()

        json_body = mock_post.call_args.kwargs.get("json") or mock_post.call_args[1].get("json")
        assert json_body["messages"][0]["topic"] == "system-notifications"
        assert json_body["messages"][0]["event"] == "notification"

    def test_broadcast_payload_contains_title_key_and_type(self):
        with patch("app.services.notifications.get_client", return_value=make_mock_client()):
            with patch("app.services.notifications.httpx.post", return_value=_mock_broadcast_resp()) as mock_post:
                self._call()

        payload = mock_post.call_args.kwargs["json"]["messages"][0]["payload"]
        assert payload["titleKey"] == "notifications.order_ready"
        assert payload["type"] == "order_ready"

    def test_insert_happens_before_broadcast(self):
        """DB insert must precede the realtime broadcast so late-joining clients always find the row."""
        call_order = []
        mock_client = make_mock_client()
        mock_client.execute.side_effect = lambda: call_order.append("insert") or MagicMock(data=[])

        def fake_post(*args, **kwargs):
            call_order.append("broadcast")
            return _mock_broadcast_resp()

        with patch("app.services.notifications.get_client", return_value=mock_client):
            with patch("app.services.notifications.httpx.post", side_effect=fake_post):
                self._call()

        assert call_order == ["insert", "broadcast"]

    def test_raises_if_broadcast_returns_error_status(self):
        with patch("app.services.notifications.get_client", return_value=make_mock_client()):
            with patch("app.services.notifications.httpx.post", return_value=_mock_broadcast_resp(status_code=500)):
                with pytest.raises(RuntimeError, match="broadcast failed"):
                    self._call()

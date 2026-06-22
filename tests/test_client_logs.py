"""Tests for POST /client-logs — anonymous client log forwarding (XC-3)."""

from unittest.mock import patch

from fastapi.testclient import TestClient


class TestClientLogs:
    def test_accepts_batch_and_forwards_to_axiom(self, client: TestClient):
        body = {
            "events": [
                {"module": "http", "action": "GET /dishes", "level": "info"},
                {"module": "payments", "action": "redsys_error", "level": "error"},
            ]
        }
        with patch("app.routers.client_logs.log_events") as mock_log:
            resp = client.post("/client-logs", json=body)
        assert resp.status_code == 202
        assert resp.json() == {"data": {"accepted": 2}, "error": None}
        forwarded = mock_log.call_args[0][0]
        assert len(forwarded) == 2

    def test_source_is_forced_server_side(self, client: TestClient):
        # A caller cannot forge events as the API/staff apps.
        body = {"events": [{"module": "x", "action": "y", "source": "🐍 api"}]}
        with patch("app.routers.client_logs.log_events") as mock_log:
            resp = client.post("/client-logs", json=body)
        assert resp.status_code == 202
        assert mock_log.call_args[0][0][0]["source"] == "📱 clients"

    def test_no_api_key_required(self, client: TestClient):
        with patch("app.routers.client_logs.log_events"):
            resp = client.post("/client-logs", json={"events": [{"module": "m", "action": "a"}]})
        assert resp.status_code == 202

    def test_empty_batch_is_accepted(self, client: TestClient):
        with patch("app.routers.client_logs.log_events") as mock_log:
            resp = client.post("/client-logs", json={"events": []})
        assert resp.status_code == 202
        assert resp.json()["data"]["accepted"] == 0
        mock_log.assert_called_once_with([])

    def test_batch_over_50_is_rejected(self, client: TestClient):
        body = {"events": [{"module": "m", "action": "a"} for _ in range(51)]}
        with patch("app.routers.client_logs.log_events"):
            resp = client.post("/client-logs", json=body)
        assert resp.status_code == 422

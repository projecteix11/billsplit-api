"""Tests for the /api/health endpoint and app-level setup."""

from unittest.mock import patch

from fastapi.testclient import TestClient

from tests.conftest import make_mock_client


class TestHealthEndpoint:
    def test_health_returns_200(self, client: TestClient):
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_health_returns_ok_status(self, client: TestClient):
        resp = client.get("/health")
        assert resp.json() == {"status": "ok"}

    def test_unknown_route_returns_404(self, client: TestClient):
        resp = client.get("/does-not-exist")
        assert resp.status_code == 404

    def test_health_allows_get_only(self, client: TestClient):
        # POST to the health endpoint should 405
        resp = client.post("/health")
        assert resp.status_code == 405


class TestReadyEndpoint:
    """XM-7: /ready is a real readiness probe (DB round-trip), unlike /health."""

    def test_ready_returns_200_when_db_reachable(self, client: TestClient):
        with patch("app.db.supabase.get_client", return_value=make_mock_client(data=[{"id": "t-1"}])):
            resp = client.get("/ready")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ready"}

    def test_ready_returns_503_when_db_unreachable(self, client: TestClient):
        with patch("app.db.supabase.get_client", side_effect=RuntimeError("db down")):
            resp = client.get("/ready")
        assert resp.status_code == 503
        assert resp.json()["status"] == "unavailable"

"""Tests for the /api/health endpoint and app-level setup."""

from fastapi.testclient import TestClient


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

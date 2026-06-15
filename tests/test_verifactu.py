"""Tests for the diner Verifactu endpoints (Option-A: routed through the API).

The diner used to read verifactu_config directly with the anon key (revoked by
the Phase 0.4 RLS lockdown) and call the edge function with the tenant *slug*.
These endpoints derive the tenant uuid server-side (get_current_tenant, overridden
to VALID_TENANT_ID in tests) and call the edge function with the service-role key.
"""
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from tests.conftest import make_mock_client


def _edge_resp(payload: dict) -> MagicMock:
    m = MagicMock()
    m.json.return_value = payload
    m.raise_for_status.return_value = None
    return m


class TestGetConfig:
    def test_returns_safe_projection(self, client: TestClient):
        row = {"enabled": True, "cert_verified": False}
        with patch("app.services.verifactu.get_client", return_value=make_mock_client(data=[row])):
            resp = client.get("/verifactu/config")
        assert resp.status_code == 200
        assert resp.json()["data"] == {"enabled": True, "cert_verified": False}

    def test_returns_null_when_no_config(self, client: TestClient):
        with patch("app.services.verifactu.get_client", return_value=make_mock_client(data=[])):
            resp = client.get("/verifactu/config")
        assert resp.status_code == 200
        assert resp.json()["data"] is None


class TestCreateInvoice:
    _body = {"orderId": "order-1", "paymentId": "pay-1", "tipoFactura": "F2"}

    def test_creates_via_edge_with_server_tenant(self, client: TestClient):
        invoice = {"id": "inv-1"}
        with patch(
            "app.services.verifactu.get_client",
            return_value=make_mock_client(data=[{"enabled": True, "cert_verified": True}]),
        ), patch(
            "app.services.verifactu.httpx.post",
            return_value=_edge_resp({"ok": True, "invoice": invoice}),
        ) as m:
            resp = client.post("/verifactu/invoice", json=self._body)
        assert resp.status_code == 200
        assert resp.json()["data"]["ok"] is True
        sent = m.call_args.kwargs["json"]
        assert sent["action"] == "create-invoice"
        assert sent["tenant_id"] == "test-tenant-uuid"  # server-derived, not a slug
        assert sent["auto_send"] is True  # from cert_verified

    def test_missing_fields_returns_422(self, client: TestClient):
        resp = client.post("/verifactu/invoice", json={"orderId": "o-1"})
        assert resp.status_code == 422


class TestGeneratePdf:
    def test_calls_edge_generate_pdf(self, client: TestClient):
        with patch(
            "app.services.verifactu.httpx.post",
            return_value=_edge_resp({"ok": True, "pdf_url": "https://x/y.pdf"}),
        ) as m:
            resp = client.post("/verifactu/invoice/inv-1/pdf")
        assert resp.status_code == 200
        assert resp.json()["data"]["pdf_url"].endswith(".pdf")
        sent = m.call_args.kwargs["json"]
        assert sent["action"] == "generate-pdf"
        assert sent["invoice_id"] == "inv-1"
        assert sent["tenant_id"] == "test-tenant-uuid"

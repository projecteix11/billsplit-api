import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_track_order_not_found(monkeypatch):
    with patch("app.services.orders.get_order_tracking", return_value=None):
        res = client.get("/orders/track/GOB-INVALID")
        assert res.status_code == 404
        assert res.json()["error"] == "Comanda no trobada"


def test_track_order_success(monkeypatch):
    mock_tracking = {
        "order_id": "c79e73b9-a43e-4e45-b448-92d1223a9736",
        "tracking_code": "GOB-C79E73",
        "table_id": "table-1",
        "table_number": 3,
        "table_label": "Taula 3",
        "status": "open",
        "subtotal": 24.50,
        "tax_amount": 2.45,
        "total": 26.95,
        "amount_paid": 26.95,
        "created_at": "2026-08-22T10:00:00Z",
        "updated_at": "2026-08-22T10:00:00Z",
        "tenant_name": "Demo Pre-Pay",
        "tenant_slug": "demo-prepay",
        "overall_stage": "in_kitchen",
        "total_items": 2,
        "pending_items": 2,
        "cooking_items": 0,
        "ready_items": 0,
        "delivered_items": 0,
        "items": [],
    }
    with patch("app.services.orders.get_order_tracking", return_value=mock_tracking):
        res = client.get("/orders/track/GOB-C79E73")
        assert res.status_code == 200
        data = res.json()["data"]
        assert data["tracking_code"] == "GOB-C79E73"
        assert data["table_number"] == 3
        assert data["overall_stage"] == "in_kitchen"

"""
Tests for:
  GET /api/dishes
  GET /api/categories

Both endpoints call service functions that delegate to supabase.select().
We patch `app.services.dishes.supabase` (the module reference used by the
service layer) so no real HTTP calls are made.
"""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from tests.conftest import make_dish, make_category


# ---------------------------------------------------------------------------
# GET /api/dishes
# ---------------------------------------------------------------------------

class TestGetDishes:
    def test_get_dishes_returns_200_with_data_envelope(self, client: TestClient):
        dishes = [make_dish(), make_dish(id="dish-2", name="Pasta Carbonara")]
        with patch("app.services.dishes.supabase") as mock_sb:
            mock_sb.select.return_value = dishes
            resp = client.get("/api/dishes")

        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body
        assert body["error"] is None

    def test_get_dishes_returns_list_of_dishes(self, client: TestClient):
        dishes = [make_dish(), make_dish(id="dish-2", name="Pasta Carbonara", price=9.0)]
        with patch("app.services.dishes.supabase") as mock_sb:
            mock_sb.select.return_value = dishes
            resp = client.get("/api/dishes")

        data = resp.json()["data"]
        assert len(data) == 2
        assert data[0]["name"] == "Pizza Margherita"
        assert data[1]["name"] == "Pasta Carbonara"

    def test_get_dishes_returns_correct_dish_fields(self, client: TestClient):
        dish = make_dish()
        with patch("app.services.dishes.supabase") as mock_sb:
            mock_sb.select.return_value = [dish]
            resp = client.get("/api/dishes")

        item = resp.json()["data"][0]
        assert item["id"] == dish["id"]
        assert item["name"] == dish["name"]
        assert item["description"] == dish["description"]
        assert item["price"] == dish["price"]
        assert item["is_available"] == dish["is_available"]
        assert item["category_id"] == dish["category_id"]

    def test_get_dishes_returns_empty_list_when_no_dishes(self, client: TestClient):
        with patch("app.services.dishes.supabase") as mock_sb:
            mock_sb.select.return_value = []
            resp = client.get("/api/dishes")

        assert resp.status_code == 200
        assert resp.json()["data"] == []

    def test_get_dishes_queries_correct_table_and_filter(self, client: TestClient):
        with patch("app.services.dishes.supabase") as mock_sb:
            mock_sb.select.return_value = []
            client.get("/api/dishes")

        mock_sb.select.assert_called_once_with("dishes", "is_available=eq.true&order=name")

    def test_get_dishes_returns_500_on_service_error(self, client: TestClient):
        with patch("app.services.dishes.supabase") as mock_sb:
            mock_sb.select.side_effect = RuntimeError("supabase 503: service unavailable")
            resp = client.get("/api/dishes")

        assert resp.status_code == 500
        body = resp.json()
        assert body["data"] is None
        assert "supabase 503" in body["error"]

    def test_get_dishes_error_response_has_correct_envelope(self, client: TestClient):
        with patch("app.services.dishes.supabase") as mock_sb:
            mock_sb.select.side_effect = RuntimeError("DB error")
            resp = client.get("/api/dishes")

        body = resp.json()
        assert "data" in body
        assert "error" in body
        assert body["data"] is None


# ---------------------------------------------------------------------------
# GET /api/categories
# ---------------------------------------------------------------------------

class TestGetCategories:
    def test_get_categories_returns_200_with_data_envelope(self, client: TestClient):
        with patch("app.services.dishes.supabase") as mock_sb:
            mock_sb.select.return_value = [make_category()]
            resp = client.get("/api/categories")

        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body
        assert body["error"] is None

    def test_get_categories_returns_list(self, client: TestClient):
        cats = [make_category(), make_category(id="cat-2", name="Pastas", sort_order=2)]
        with patch("app.services.dishes.supabase") as mock_sb:
            mock_sb.select.return_value = cats
            resp = client.get("/api/categories")

        data = resp.json()["data"]
        assert len(data) == 2

    def test_get_categories_returns_correct_fields(self, client: TestClient):
        cat = make_category()
        with patch("app.services.dishes.supabase") as mock_sb:
            mock_sb.select.return_value = [cat]
            resp = client.get("/api/categories")

        item = resp.json()["data"][0]
        assert item["id"] == cat["id"]
        assert item["name"] == cat["name"]
        assert item["sort_order"] == cat["sort_order"]

    def test_get_categories_returns_empty_list(self, client: TestClient):
        with patch("app.services.dishes.supabase") as mock_sb:
            mock_sb.select.return_value = []
            resp = client.get("/api/categories")

        assert resp.json()["data"] == []

    def test_get_categories_queries_correct_table(self, client: TestClient):
        with patch("app.services.dishes.supabase") as mock_sb:
            mock_sb.select.return_value = []
            client.get("/api/categories")

        mock_sb.select.assert_called_once_with("dish_categories", "order=sort_order")

    def test_get_categories_returns_500_on_error(self, client: TestClient):
        with patch("app.services.dishes.supabase") as mock_sb:
            mock_sb.select.side_effect = RuntimeError("connection timeout")
            resp = client.get("/api/categories")

        assert resp.status_code == 500
        body = resp.json()
        assert body["data"] is None
        assert "connection timeout" in body["error"]

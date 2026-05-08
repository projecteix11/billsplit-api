"""
Tests for:
  GET /api/dishes
  GET /api/categories
  PATCH /api/dishes/{id}
  DELETE /api/dishes/{id}
  PUT /api/dishes/{id}/allergens
  PATCH/DELETE /api/dishes/{id}/ingredients/{ing_id}
"""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from tests.conftest import (
    make_dish, make_category, make_mock_client,
    VALID_TENANT_ID, VALID_TOKEN, VALID_USER_ID,
)


def _auth_headers() -> dict:
    return {"Authorization": f"Bearer {VALID_TOKEN}"}


# ---------------------------------------------------------------------------
# GET /api/dishes
# ---------------------------------------------------------------------------

class TestGetDishes:
    def test_get_dishes_returns_200_with_data_envelope(self, client: TestClient):
        dishes = [make_dish(), make_dish(id="dish-2", name="Pasta Carbonara")]
        with patch("app.services.dishes.get_client") as mock_gc:
            mock_gc.return_value = make_mock_client(data=dishes)
            resp = client.get("/dishes")

        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body
        assert body["error"] is None

    def test_get_dishes_returns_list_of_dishes(self, client: TestClient):
        dishes = [make_dish(), make_dish(id="dish-2", name="Pasta Carbonara", price=9.0)]
        with patch("app.services.dishes.get_client") as mock_gc:
            mock_gc.return_value = make_mock_client(data=dishes)
            resp = client.get("/dishes")

        data = resp.json()["data"]
        assert len(data) == 2
        assert data[0]["name"] == "Pizza Margherita"
        assert data[1]["name"] == "Pasta Carbonara"

    def test_get_dishes_returns_correct_dish_fields(self, client: TestClient):
        dish = make_dish()
        with patch("app.services.dishes.get_client") as mock_gc:
            mock_gc.return_value = make_mock_client(data=[dish])
            resp = client.get("/dishes")

        item = resp.json()["data"][0]
        assert item["id"] == dish["id"]
        assert item["name"] == dish["name"]
        assert item["description"] == dish["description"]
        assert item["price"] == dish["price"]
        assert item["is_available"] == dish["is_available"]
        assert item["category_id"] == dish["category_id"]

    def test_get_dishes_returns_empty_list_when_no_dishes(self, client: TestClient):
        with patch("app.services.dishes.get_client") as mock_gc:
            mock_gc.return_value = make_mock_client(data=[])
            resp = client.get("/dishes")

        assert resp.status_code == 200
        assert resp.json()["data"] == []

    def test_get_dishes_returns_500_on_service_error(self, client: TestClient):
        mock_q = make_mock_client()
        mock_q.execute.side_effect = RuntimeError("supabase 503: service unavailable")
        with patch("app.services.dishes.get_client") as mock_gc:
            mock_gc.return_value = mock_q
            resp = client.get("/dishes")

        assert resp.status_code == 500
        body = resp.json()
        assert body["data"] is None
        assert "supabase 503" in body["error"]

    def test_get_dishes_error_response_has_correct_envelope(self, client: TestClient):
        mock_q = make_mock_client()
        mock_q.execute.side_effect = RuntimeError("DB error")
        with patch("app.services.dishes.get_client") as mock_gc:
            mock_gc.return_value = mock_q
            resp = client.get("/dishes")

        body = resp.json()
        assert "data" in body
        assert "error" in body
        assert body["data"] is None


# ---------------------------------------------------------------------------
# GET /api/categories
# ---------------------------------------------------------------------------

class TestGetCategories:
    def test_get_categories_returns_200_with_data_envelope(self, client: TestClient):
        with patch("app.services.dishes.get_client") as mock_gc:
            mock_gc.return_value = make_mock_client(data=[make_category()])
            resp = client.get("/categories")

        assert resp.status_code == 200
        body = resp.json()
        assert "data" in body
        assert body["error"] is None

    def test_get_categories_returns_list(self, client: TestClient):
        cats = [make_category(), make_category(id="cat-2", name="Pastas", sort_order=2)]
        with patch("app.services.dishes.get_client") as mock_gc:
            mock_gc.return_value = make_mock_client(data=cats)
            resp = client.get("/categories")

        data = resp.json()["data"]
        assert len(data) == 2

    def test_get_categories_returns_correct_fields(self, client: TestClient):
        cat = make_category()
        with patch("app.services.dishes.get_client") as mock_gc:
            mock_gc.return_value = make_mock_client(data=[cat])
            resp = client.get("/categories")

        item = resp.json()["data"][0]
        assert item["id"] == cat["id"]
        assert item["name"] == cat["name"]
        assert item["sort_order"] == cat["sort_order"]

    def test_get_categories_returns_empty_list(self, client: TestClient):
        with patch("app.services.dishes.get_client") as mock_gc:
            mock_gc.return_value = make_mock_client(data=[])
            resp = client.get("/categories")

        assert resp.json()["data"] == []

    def test_get_categories_returns_500_on_error(self, client: TestClient):
        mock_q = make_mock_client()
        mock_q.execute.side_effect = RuntimeError("connection timeout")
        with patch("app.services.dishes.get_client") as mock_gc:
            mock_gc.return_value = mock_q
            resp = client.get("/categories")

        assert resp.status_code == 500
        body = resp.json()
        assert body["data"] is None
        assert "connection timeout" in body["error"]


# ---------------------------------------------------------------------------
# PATCH /dishes/{dish_id} — ownership check
# ---------------------------------------------------------------------------

class TestUpdateDish:
    def test_update_dish_returns_200_for_correct_tenant(self, client: TestClient):
        dish = make_dish()
        mock_q = make_mock_client()
        mock_q.execute.side_effect = [
            MagicMock(data=[{"id": "dish-1"}]),  # _assert_dish_owner
            MagicMock(data=None),                 # update
            MagicMock(data=[dish]),               # get_dish_by_id after update
        ]
        with patch("app.services.dishes.get_client") as mock_gc:
            mock_gc.return_value = mock_q
            with patch("app.db.supabase.verify_token_full", return_value=(VALID_USER_ID, VALID_TENANT_ID, "staff")):
                resp = client.patch("/dishes/dish-1", json={"name": "Updated"}, headers=_auth_headers())

        assert resp.status_code == 200

    def test_update_dish_returns_404_for_wrong_tenant(self, client: TestClient):
        with patch("app.services.dishes.get_client") as mock_gc:
            mock_gc.return_value = make_mock_client(data=[])  # _assert_dish_owner finds nothing
            with patch("app.db.supabase.verify_token_full", return_value=(VALID_USER_ID, VALID_TENANT_ID, "staff")):
                resp = client.patch("/dishes/dish-other", json={"name": "Hack"}, headers=_auth_headers())

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /dishes/{dish_id} — ownership check
# ---------------------------------------------------------------------------

class TestDeleteDish:
    def test_delete_dish_returns_200_for_correct_tenant(self, client: TestClient):
        mock_q = make_mock_client()
        mock_q.execute.side_effect = [
            MagicMock(data=[{"id": "dish-1"}]),  # _assert_dish_owner
            MagicMock(data=None),                 # delete
        ]
        with patch("app.services.dishes.get_client") as mock_gc:
            mock_gc.return_value = mock_q
            with patch("app.db.supabase.verify_token_full", return_value=(VALID_USER_ID, VALID_TENANT_ID, "staff")):
                resp = client.delete("/dishes/dish-1", headers=_auth_headers())

        assert resp.status_code == 200

    def test_delete_dish_returns_404_for_wrong_tenant(self, client: TestClient):
        with patch("app.services.dishes.get_client") as mock_gc:
            mock_gc.return_value = make_mock_client(data=[])
            with patch("app.db.supabase.verify_token_full", return_value=(VALID_USER_ID, VALID_TENANT_ID, "staff")):
                resp = client.delete("/dishes/dish-other", headers=_auth_headers())

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PUT /dishes/{dish_id}/allergens — ownership check
# ---------------------------------------------------------------------------

class TestSetDishAllergens:
    def test_set_allergens_returns_200_for_correct_tenant(self, client: TestClient):
        mock_q = make_mock_client()
        mock_q.execute.side_effect = [
            MagicMock(data=[{"id": "dish-1"}]),  # _assert_dish_owner
            MagicMock(data=None),                 # delete existing allergens
        ]
        with patch("app.services.dishes.get_client") as mock_gc:
            mock_gc.return_value = mock_q
            with patch("app.db.supabase.verify_token_full", return_value=(VALID_USER_ID, VALID_TENANT_ID, "staff")):
                resp = client.put("/dishes/dish-1/allergens", json={"allergen_ids": []}, headers=_auth_headers())

        assert resp.status_code == 200

    def test_set_allergens_returns_404_for_wrong_tenant(self, client: TestClient):
        with patch("app.services.dishes.get_client") as mock_gc:
            mock_gc.return_value = make_mock_client(data=[])
            with patch("app.db.supabase.verify_token_full", return_value=(VALID_USER_ID, VALID_TENANT_ID, "staff")):
                resp = client.put("/dishes/dish-other/allergens", json={"allergen_ids": []}, headers=_auth_headers())

        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PATCH/DELETE /dishes/{dish_id}/ingredients — ownership check
# ---------------------------------------------------------------------------

class TestDishIngredientOwnership:
    def test_update_ingredient_returns_404_for_wrong_tenant(self, client: TestClient):
        with patch("app.services.dishes.get_client") as mock_gc:
            mock_gc.return_value = make_mock_client(data=[])
            with patch("app.db.supabase.verify_token_full", return_value=(VALID_USER_ID, VALID_TENANT_ID, "staff")):
                resp = client.patch(
                    "/dishes/dish-other/ingredients/ing-1",
                    json={"name": "Hack"},
                    headers=_auth_headers(),
                )

        assert resp.status_code == 404

    def test_delete_ingredient_returns_404_for_wrong_tenant(self, client: TestClient):
        with patch("app.services.dishes.get_client") as mock_gc:
            mock_gc.return_value = make_mock_client(data=[])
            with patch("app.db.supabase.verify_token_full", return_value=(VALID_USER_ID, VALID_TENANT_ID, "staff")):
                resp = client.delete(
                    "/dishes/dish-other/ingredients/ing-1",
                    headers=_auth_headers(),
                )

        assert resp.status_code == 404

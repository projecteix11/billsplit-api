"""
Tests for daily_menus ownership checks (IDOR fix #32).

Covers PATCH/DELETE /daily-menus/{id}, POST/PATCH/DELETE sections,
POST/PATCH/DELETE items — all must return 404 for wrong-tenant resources.
"""

import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from tests.conftest import VALID_TOKEN, VALID_USER_ID, VALID_TENANT_ID


def _auth_headers() -> dict:
    return {"Authorization": f"Bearer {VALID_TOKEN}"}


def _owner_menu() -> list:
    return [{"id": "menu-1"}]


def _owner_section() -> list:
    return [{"id": "section-1", "menu": {"tenant_id": VALID_TENANT_ID}}]


def _owner_item() -> list:
    return [{"id": "item-1", "section": {"menu": {"tenant_id": VALID_TENANT_ID}}}]


# ---------------------------------------------------------------------------
# PATCH /daily-menus/{menu_id}
# ---------------------------------------------------------------------------

class TestUpdateDailyMenu:
    def test_returns_200_for_correct_tenant(self, client: TestClient):
        with patch("app.services.daily_menus.supabase") as mock_sb:
            mock_sb.select.side_effect = [
                _owner_menu(),  # _assert_menu_owner
                [],             # get_daily_menu_by_id (returns None)
            ]
            mock_sb.update.return_value = None
            with patch("app.db.supabase.verify_token_full", return_value=(VALID_USER_ID, VALID_TENANT_ID, "staff")):
                resp = client.patch("/daily-menus/menu-1", json={"name": "Updated"}, headers=_auth_headers())

        assert resp.status_code == 200

    def test_returns_404_for_wrong_tenant(self, client: TestClient):
        with patch("app.services.daily_menus.supabase") as mock_sb:
            mock_sb.select.return_value = []  # _assert_menu_owner finds nothing
            with patch("app.db.supabase.verify_token_full", return_value=(VALID_USER_ID, VALID_TENANT_ID, "staff")):
                resp = client.patch("/daily-menus/other-menu", json={"name": "Hack"}, headers=_auth_headers())

        assert resp.status_code == 404
        mock_sb.update.assert_not_called()


# ---------------------------------------------------------------------------
# DELETE /daily-menus/{menu_id}
# ---------------------------------------------------------------------------

class TestDeleteDailyMenu:
    def test_returns_200_for_correct_tenant(self, client: TestClient):
        with patch("app.services.daily_menus.supabase") as mock_sb:
            mock_sb.select.return_value = _owner_menu()
            mock_sb.delete.return_value = None
            with patch("app.db.supabase.verify_token_full", return_value=(VALID_USER_ID, VALID_TENANT_ID, "staff")):
                resp = client.delete("/daily-menus/menu-1", headers=_auth_headers())

        assert resp.status_code == 200

    def test_returns_404_for_wrong_tenant(self, client: TestClient):
        with patch("app.services.daily_menus.supabase") as mock_sb:
            mock_sb.select.return_value = []
            with patch("app.db.supabase.verify_token_full", return_value=(VALID_USER_ID, VALID_TENANT_ID, "staff")):
                resp = client.delete("/daily-menus/other-menu", headers=_auth_headers())

        assert resp.status_code == 404
        mock_sb.delete.assert_not_called()


# ---------------------------------------------------------------------------
# POST /daily-menus/{menu_id}/sections
# ---------------------------------------------------------------------------

class TestCreateSection:
    def test_returns_201_for_correct_tenant(self, client: TestClient):
        section_row = {"id": "sec-1", "menu_id": "menu-1", "name": "Primeros", "sort_order": 1, "max_choices": 3}
        with patch("app.services.daily_menus.supabase") as mock_sb:
            mock_sb.select.return_value = _owner_menu()
            mock_sb.insert.return_value = [section_row]
            with patch("app.db.supabase.verify_token_full", return_value=(VALID_USER_ID, VALID_TENANT_ID, "staff")):
                resp = client.post(
                    "/daily-menus/menu-1/sections",
                    json={"name": "Primeros", "sort_order": 1},
                    headers=_auth_headers(),
                )

        assert resp.status_code == 201

    def test_returns_404_for_wrong_tenant(self, client: TestClient):
        with patch("app.services.daily_menus.supabase") as mock_sb:
            mock_sb.select.return_value = []
            with patch("app.db.supabase.verify_token_full", return_value=(VALID_USER_ID, VALID_TENANT_ID, "staff")):
                resp = client.post(
                    "/daily-menus/other-menu/sections",
                    json={"name": "Hack", "sort_order": 1},
                    headers=_auth_headers(),
                )

        assert resp.status_code == 404
        mock_sb.insert.assert_not_called()


# ---------------------------------------------------------------------------
# PATCH /daily-menu-sections/{section_id}
# ---------------------------------------------------------------------------

class TestUpdateSection:
    def test_returns_200_for_correct_tenant(self, client: TestClient):
        with patch("app.services.daily_menus.supabase") as mock_sb:
            mock_sb.select.return_value = _owner_section()
            mock_sb.update.return_value = None
            with patch("app.db.supabase.verify_token_full", return_value=(VALID_USER_ID, VALID_TENANT_ID, "staff")):
                resp = client.patch(
                    "/daily-menu-sections/section-1",
                    json={"name": "Updated"},
                    headers=_auth_headers(),
                )

        assert resp.status_code == 200

    def test_returns_404_for_wrong_tenant(self, client: TestClient):
        with patch("app.services.daily_menus.supabase") as mock_sb:
            mock_sb.select.return_value = [{"id": "section-1", "menu": {"tenant_id": "other"}}]
            with patch("app.db.supabase.verify_token_full", return_value=(VALID_USER_ID, VALID_TENANT_ID, "staff")):
                resp = client.patch(
                    "/daily-menu-sections/section-1",
                    json={"name": "Hack"},
                    headers=_auth_headers(),
                )

        assert resp.status_code == 404
        mock_sb.update.assert_not_called()


# ---------------------------------------------------------------------------
# DELETE /daily-menu-sections/{section_id}
# ---------------------------------------------------------------------------

class TestDeleteSection:
    def test_returns_200_for_correct_tenant(self, client: TestClient):
        with patch("app.services.daily_menus.supabase") as mock_sb:
            mock_sb.select.return_value = _owner_section()
            mock_sb.delete.return_value = None
            with patch("app.db.supabase.verify_token_full", return_value=(VALID_USER_ID, VALID_TENANT_ID, "staff")):
                resp = client.delete("/daily-menu-sections/section-1", headers=_auth_headers())

        assert resp.status_code == 200

    def test_returns_404_for_wrong_tenant(self, client: TestClient):
        with patch("app.services.daily_menus.supabase") as mock_sb:
            mock_sb.select.return_value = [{"id": "section-1", "menu": {"tenant_id": "other"}}]
            with patch("app.db.supabase.verify_token_full", return_value=(VALID_USER_ID, VALID_TENANT_ID, "staff")):
                resp = client.delete("/daily-menu-sections/section-1", headers=_auth_headers())

        assert resp.status_code == 404
        mock_sb.delete.assert_not_called()


# ---------------------------------------------------------------------------
# POST /daily-menu-sections/{section_id}/items
# ---------------------------------------------------------------------------

class TestCreateItem:
    def test_returns_201_for_correct_tenant(self, client: TestClient):
        item_row = {"id": "item-1", "section_id": "section-1", "name": "Sopa", "sort_order": 1, "dish_id": None, "description": None, "supplement_price": 0.0}
        with patch("app.services.daily_menus.supabase") as mock_sb:
            mock_sb.select.return_value = _owner_section()
            mock_sb.insert.return_value = [item_row]
            with patch("app.db.supabase.verify_token_full", return_value=(VALID_USER_ID, VALID_TENANT_ID, "staff")):
                resp = client.post(
                    "/daily-menu-sections/section-1/items",
                    json={"name": "Sopa", "sort_order": 1},
                    headers=_auth_headers(),
                )

        assert resp.status_code == 201

    def test_returns_404_for_wrong_tenant(self, client: TestClient):
        with patch("app.services.daily_menus.supabase") as mock_sb:
            mock_sb.select.return_value = [{"id": "section-1", "menu": {"tenant_id": "other"}}]
            with patch("app.db.supabase.verify_token_full", return_value=(VALID_USER_ID, VALID_TENANT_ID, "staff")):
                resp = client.post(
                    "/daily-menu-sections/section-1/items",
                    json={"name": "Hack", "sort_order": 1},
                    headers=_auth_headers(),
                )

        assert resp.status_code == 404
        mock_sb.insert.assert_not_called()


# ---------------------------------------------------------------------------
# PATCH /daily-menu-items/{item_id}
# ---------------------------------------------------------------------------

class TestUpdateItem:
    def test_returns_200_for_correct_tenant(self, client: TestClient):
        with patch("app.services.daily_menus.supabase") as mock_sb:
            mock_sb.select.return_value = _owner_item()
            mock_sb.update.return_value = None
            with patch("app.db.supabase.verify_token_full", return_value=(VALID_USER_ID, VALID_TENANT_ID, "staff")):
                resp = client.patch(
                    "/daily-menu-items/item-1",
                    json={"name": "Updated"},
                    headers=_auth_headers(),
                )

        assert resp.status_code == 200

    def test_returns_404_for_wrong_tenant(self, client: TestClient):
        with patch("app.services.daily_menus.supabase") as mock_sb:
            mock_sb.select.return_value = [{"id": "item-1", "section": {"menu": {"tenant_id": "other"}}}]
            with patch("app.db.supabase.verify_token_full", return_value=(VALID_USER_ID, VALID_TENANT_ID, "staff")):
                resp = client.patch(
                    "/daily-menu-items/item-1",
                    json={"name": "Hack"},
                    headers=_auth_headers(),
                )

        assert resp.status_code == 404
        mock_sb.update.assert_not_called()


# ---------------------------------------------------------------------------
# DELETE /daily-menu-items/{item_id}
# ---------------------------------------------------------------------------

class TestDeleteItem:
    def test_returns_200_for_correct_tenant(self, client: TestClient):
        with patch("app.services.daily_menus.supabase") as mock_sb:
            mock_sb.select.return_value = _owner_item()
            mock_sb.delete.return_value = None
            with patch("app.db.supabase.verify_token_full", return_value=(VALID_USER_ID, VALID_TENANT_ID, "staff")):
                resp = client.delete("/daily-menu-items/item-1", headers=_auth_headers())

        assert resp.status_code == 200

    def test_returns_404_for_wrong_tenant(self, client: TestClient):
        with patch("app.services.daily_menus.supabase") as mock_sb:
            mock_sb.select.return_value = [{"id": "item-1", "section": {"menu": {"tenant_id": "other"}}}]
            with patch("app.db.supabase.verify_token_full", return_value=(VALID_USER_ID, VALID_TENANT_ID, "staff")):
                resp = client.delete("/daily-menu-items/item-1", headers=_auth_headers())

        assert resp.status_code == 404
        mock_sb.delete.assert_not_called()

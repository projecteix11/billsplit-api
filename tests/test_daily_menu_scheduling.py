from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import patch
import pytest

from app.services.daily_menus import is_menu_active_now

def test_is_menu_active_now_no_restriction():
    assert is_menu_active_now({}) is True
    assert is_menu_active_now({"schedule_restriction": None}) is True
    assert is_menu_active_now({"schedule_restriction": {"enabled": False}}) is True

@patch("app.services.daily_menus.datetime")
def test_is_menu_active_now_days(mock_datetime):
    # 2026-07-13 is a Monday
    mock_now = datetime(2026, 7, 13, 10, 0, tzinfo=ZoneInfo("Europe/Madrid"))
    mock_datetime.now.return_value = mock_now

    # Menu active on Monday/Tuesday
    assert is_menu_active_now({
        "schedule_restriction": {
            "enabled": True,
            "days": ["Monday", "Tuesday"]
        }
    }) is True

    # Menu active only on Friday
    assert is_menu_active_now({
        "schedule_restriction": {
            "enabled": True,
            "days": ["friday"]
        }
    }) is False

@patch("app.services.daily_menus.datetime")
def test_is_menu_active_now_slots(mock_datetime):
    # Morning slot (06:00 - 12:00)
    # Let's mock time to be 09:30 on a Monday
    mock_datetime.now.return_value = datetime(2026, 7, 13, 9, 30, tzinfo=ZoneInfo("Europe/Madrid"))

    # Active for morning slot
    assert is_menu_active_now({
        "schedule_restriction": {
            "enabled": True,
            "slots": ["morning"]
        }
    }) is True

    # Inactive for afternoon slot
    assert is_menu_active_now({
        "schedule_restriction": {
            "enabled": True,
            "slots": ["afternoon"]
        }
    }) is False

    # Afternoon slot (12:00 - 20:00)
    # Let's mock time to be 15:00
    mock_datetime.now.return_value = datetime(2026, 7, 13, 15, 0, tzinfo=ZoneInfo("Europe/Madrid"))

    assert is_menu_active_now({
        "schedule_restriction": {
            "enabled": True,
            "slots": ["afternoon"]
        }
    }) is True

    # Night slot (20:00 - 06:00)
    # Let's mock time to be 23:30
    mock_datetime.now.return_value = datetime(2026, 7, 13, 23, 30, tzinfo=ZoneInfo("Europe/Madrid"))
    assert is_menu_active_now({
        "schedule_restriction": {
            "enabled": True,
            "slots": ["night"]
        }
    }) is True

    # Let's mock time to be 02:00 (wrapping)
    mock_datetime.now.return_value = datetime(2026, 7, 14, 2, 0, tzinfo=ZoneInfo("Europe/Madrid"))
    assert is_menu_active_now({
        "schedule_restriction": {
            "enabled": True,
            "slots": ["night"]
        }
    }) is True

@patch("app.services.daily_menus.datetime")
def test_is_menu_active_now_custom_hours(mock_datetime):
    # Test normal custom hour range (e.g. 13:00 to 16:00)
    # Active at 14:30
    mock_datetime.now.return_value = datetime(2026, 7, 13, 14, 30, tzinfo=ZoneInfo("Europe/Madrid"))
    assert is_menu_active_now({
        "schedule_restriction": {
            "enabled": True,
            "start_hour": "13:00",
            "end_hour": "16:00"
        }
    }) is True

    # Inactive at 17:00
    mock_datetime.now.return_value = datetime(2026, 7, 13, 17, 0, tzinfo=ZoneInfo("Europe/Madrid"))
    assert is_menu_active_now({
        "schedule_restriction": {
            "enabled": True,
            "start_hour": "13:00",
            "end_hour": "16:00"
        }
    }) is False

    # Test midnight wrapping custom hour range (e.g. 22:00 to 02:00)
    # Active at 23:00
    mock_datetime.now.return_value = datetime(2026, 7, 13, 23, 0, tzinfo=ZoneInfo("Europe/Madrid"))
    assert is_menu_active_now({
        "schedule_restriction": {
            "enabled": True,
            "start_hour": "22:00",
            "end_hour": "02:00"
        }
    }) is True

    # Active at 01:00
    mock_datetime.now.return_value = datetime(2026, 7, 14, 1, 0, tzinfo=ZoneInfo("Europe/Madrid"))
    assert is_menu_active_now({
        "schedule_restriction": {
            "enabled": True,
            "start_hour": "22:00",
            "end_hour": "02:00"
        }
    }) is True

    # Inactive at 03:00
    mock_datetime.now.return_value = datetime(2026, 7, 14, 3, 0, tzinfo=ZoneInfo("Europe/Madrid"))
    assert is_menu_active_now({
        "schedule_restriction": {
            "enabled": True,
            "start_hour": "22:00",
            "end_hour": "02:00"
        }
    }) is False

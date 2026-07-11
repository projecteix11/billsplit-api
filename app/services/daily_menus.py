from __future__ import annotations
from datetime import datetime
from zoneinfo import ZoneInfo

from app.db.supabase import get_client
from app.models import (
    CreateDailyMenuBody,
    CreateDailyMenuItemBody,
    CreateDailyMenuSectionBody,
    DailyMenu,
    DailyMenuItem,
    DailyMenuSection,
    UpdateDailyMenuBody,
    UpdateDailyMenuItemBody,
    UpdateDailyMenuSectionBody,
)

_MENU_SELECT = "*,sections:daily_menu_sections(id,menu_id,name,sort_order,max_choices)"


# ── Helpers ────────────────────────────────────────────────────────────────


def _hydrate_menus(rows: list[dict]) -> list[DailyMenu]:
    """Parse menu rows with sections, then fetch and attach items."""
    if not rows:
        return []

    # Collect all section IDs
    section_ids: list[str] = []
    for row in rows:
        for s in (row.get("sections") or []):
            section_ids.append(s["id"])

    # Batch-fetch all items for these sections
    items_by_section: dict[str, list[DailyMenuItem]] = {}
    if section_ids:
        all_items = get_client().table("daily_menu_items").select("*").in_("section_id", section_ids).order("sort_order").execute().data or []
        for it in all_items:
            sid = it["section_id"]
            items_by_section.setdefault(sid, []).append(DailyMenuItem(**it))

    # Build models
    menus: list[DailyMenu] = []
    for row in rows:
        raw_sections = row.pop("sections", []) or []
        sections = []
        for s in raw_sections:
            items = items_by_section.get(s["id"], [])
            sections.append(DailyMenuSection(**s, items=items))
        sections.sort(key=lambda x: x.sort_order)
        row.pop("tenant_id", None)
        menus.append(DailyMenu(**row, sections=sections))
    return menus


# ── Ownership helpers ─────────────────────────────────────────────────────


def _assert_menu_owner(menu_id: str, tenant_id: str) -> None:
    rows = get_client().table("daily_menus").select("id").eq("id", menu_id).eq("tenant_id", tenant_id).limit(1).execute().data or []
    if not rows:
        raise ValueError(f"daily menu {menu_id} not found")


def _assert_section_owner(section_id: str, tenant_id: str) -> None:
    rows = get_client().table("daily_menu_sections").select("id,menu:daily_menus(tenant_id)").eq("id", section_id).limit(1).execute().data or []
    if not rows or rows[0].get("menu", {}).get("tenant_id") != tenant_id:
        raise ValueError(f"daily menu section {section_id} not found")


def _assert_item_owner_menu(item_id: str, tenant_id: str) -> None:
    rows = get_client().table("daily_menu_items").select("id,section:daily_menu_sections(menu:daily_menus(tenant_id))").eq("id", item_id).limit(1).execute().data or []
    if not rows or rows[0].get("section", {}).get("menu", {}).get("tenant_id") != tenant_id:
        raise ValueError(f"daily menu item {item_id} not found")


# ── Daily menus CRUD ──────────────────────────────────────────────────────


def is_menu_active_now(menu_data: dict) -> bool:
    restriction = menu_data.get("schedule_restriction")
    if not restriction or not restriction.get("enabled"):
        return True

    local_now = datetime.now(ZoneInfo("Europe/Madrid"))

    # 1. Day check
    days = restriction.get("days", [])
    if days:
        current_day = local_now.strftime("%A").lower()
        if current_day not in [d.lower() for d in days]:
            return False

    # 2. Time check
    current_time_str = local_now.strftime("%H:%M") # "HH:MM"

    # Custom hours check
    has_custom_hours = False
    start_hour = restriction.get("start_hour")
    end_hour = restriction.get("end_hour")
    if start_hour and end_hour:
        has_custom_hours = True
        if start_hour <= end_hour:
            if not (start_hour <= current_time_str <= end_hour):
                return False
        else:
            if not (current_time_str >= start_hour or current_time_str <= end_hour):
                return False

    if not has_custom_hours:
        # Check slots
        slots = restriction.get("slots", [])
        if slots:
            in_slot = False
            for slot in slots:
                if slot == "morning":
                    if "06:00" <= current_time_str < "12:00":
                        in_slot = True
                elif slot == "afternoon":
                    if "12:00" <= current_time_str < "20:00":
                        in_slot = True
                elif slot == "night":
                    if current_time_str >= "20:00" or current_time_str < "06:00":
                        in_slot = True
            if not in_slot:
                return False

    return True


def get_daily_menus(tenant_id: str) -> list[DailyMenu]:
    """Active menus only (public / client)."""
    rows = get_client().table("daily_menus").select(_MENU_SELECT).eq("tenant_id", tenant_id).eq("is_active", True).order("created_at", desc=True).execute().data or []
    active_rows = [r for r in rows if is_menu_active_now(r)]
    return _hydrate_menus(active_rows)


def get_all_daily_menus(tenant_id: str) -> list[DailyMenu]:
    """All menus including inactive (management)."""
    rows = get_client().table("daily_menus").select(_MENU_SELECT).eq("tenant_id", tenant_id).order("created_at", desc=True).execute().data or []
    return _hydrate_menus(rows)


def get_daily_menu_by_id(menu_id: str, tenant_id: str | None = None) -> DailyMenu | None:
    query = get_client().table("daily_menus").select(_MENU_SELECT).eq("id", menu_id)
    if tenant_id:
        query = query.eq("tenant_id", tenant_id)
    rows = query.limit(1).execute().data or []
    menus = _hydrate_menus(rows)
    return menus[0] if menus else None


def create_daily_menu(body: CreateDailyMenuBody, tenant_id: str) -> DailyMenu:
    data = body.model_dump(exclude_none=True)
    data["tenant_id"] = tenant_id
    inserted = get_client().table("daily_menus").insert(data).execute().data
    if not inserted:
        raise RuntimeError("failed to create daily menu")
    menu = get_daily_menu_by_id(inserted[0]["id"], tenant_id)
    if not menu:
        raise RuntimeError("failed to read created daily menu")
    return menu


def update_daily_menu(menu_id: str, body: UpdateDailyMenuBody, tenant_id: str) -> None:
    _assert_menu_owner(menu_id, tenant_id)
    patch = body.model_dump(exclude_none=True)
    if "schedule_restriction" in body.model_fields_set:
        patch["schedule_restriction"] = body.schedule_restriction
    if not patch:
        return
    get_client().table("daily_menus").update(patch).eq("id", menu_id).execute()


def delete_daily_menu(menu_id: str, tenant_id: str) -> None:
    _assert_menu_owner(menu_id, tenant_id)
    get_client().table("daily_menus").delete().eq("id", menu_id).execute()


# ── Sections CRUD ─────────────────────────────────────────────────────────


def create_section(menu_id: str, body: CreateDailyMenuSectionBody, tenant_id: str) -> DailyMenuSection:
    _assert_menu_owner(menu_id, tenant_id)
    data = body.model_dump(exclude_none=True)
    data["menu_id"] = menu_id
    inserted = get_client().table("daily_menu_sections").insert(data).execute().data
    if not inserted:
        raise RuntimeError("failed to create section")
    row = inserted[0]
    return DailyMenuSection(**row, items=[])


def update_section(section_id: str, body: UpdateDailyMenuSectionBody, tenant_id: str) -> None:
    _assert_section_owner(section_id, tenant_id)
    patch = body.model_dump(exclude_none=True)
    if not patch:
        return
    get_client().table("daily_menu_sections").update(patch).eq("id", section_id).execute()


def delete_section(section_id: str, tenant_id: str) -> None:
    _assert_section_owner(section_id, tenant_id)
    get_client().table("daily_menu_sections").delete().eq("id", section_id).execute()


# ── Items CRUD ────────────────────────────────────────────────────────────


def create_item(section_id: str, body: CreateDailyMenuItemBody, tenant_id: str) -> DailyMenuItem:
    _assert_section_owner(section_id, tenant_id)
    data = body.model_dump(exclude_none=True)
    data["section_id"] = section_id
    inserted = get_client().table("daily_menu_items").insert(data).execute().data
    if not inserted:
        raise RuntimeError("failed to create item")
    return DailyMenuItem(**inserted[0])


def update_item(item_id: str, body: UpdateDailyMenuItemBody, tenant_id: str) -> None:
    _assert_item_owner_menu(item_id, tenant_id)
    patch = body.model_dump(exclude_none=True)
    if not patch:
        return
    get_client().table("daily_menu_items").update(patch).eq("id", item_id).execute()


def delete_item(item_id: str, tenant_id: str) -> None:
    _assert_item_owner_menu(item_id, tenant_id)
    get_client().table("daily_menu_items").delete().eq("id", item_id).execute()

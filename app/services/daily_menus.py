from __future__ import annotations

from app.db import supabase
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

# ── PostgREST select (1-level deep: menus → sections) ────────────────────

_MENU_SELECT = (
    "select=*,sections:daily_menu_sections(id,menu_id,name,sort_order,max_choices)"
    "&order=created_at.desc"
    "&daily_menu_sections.order=sort_order"
)


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
        all_items = supabase.select(
            "daily_menu_items",
            f"select=*&section_id=in.({','.join(section_ids)})&order=sort_order",
        )
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


# ── Daily menus CRUD ──────────────────────────────────────────────────────


def get_daily_menus() -> list[DailyMenu]:
    """Active menus only (public / client)."""
    rows = supabase.select(
        "daily_menus",
        f"{_MENU_SELECT}&is_active=eq.true",
    )
    return _hydrate_menus(rows)


def get_all_daily_menus() -> list[DailyMenu]:
    """All menus including inactive (management)."""
    rows = supabase.select(
        "daily_menus",
        f"{_MENU_SELECT}",
    )
    return _hydrate_menus(rows)


def get_daily_menu_by_id(menu_id: str) -> DailyMenu | None:
    rows = supabase.select(
        "daily_menus",
        f"{_MENU_SELECT}&id=eq.{menu_id}&limit=1",
    )
    menus = _hydrate_menus(rows)
    return menus[0] if menus else None


def create_daily_menu(body: CreateDailyMenuBody) -> DailyMenu:
    data = body.model_dump(exclude_none=True)
    inserted = supabase.insert("daily_menus", data, return_result=True)
    if not inserted:
        raise RuntimeError("failed to create daily menu")
    menu = get_daily_menu_by_id(inserted[0]["id"])
    if not menu:
        raise RuntimeError("failed to read created daily menu")
    return menu


def update_daily_menu(menu_id: str, body: UpdateDailyMenuBody) -> None:
    patch = body.model_dump(exclude_none=True)
    if not patch:
        return
    supabase.update("daily_menus", f"id=eq.{menu_id}", patch)


def delete_daily_menu(menu_id: str) -> None:
    supabase.delete("daily_menus", f"id=eq.{menu_id}")


# ── Sections CRUD ─────────────────────────────────────────────────────────


def create_section(menu_id: str, body: CreateDailyMenuSectionBody) -> DailyMenuSection:
    data = body.model_dump(exclude_none=True)
    data["menu_id"] = menu_id
    inserted = supabase.insert("daily_menu_sections", data, return_result=True)
    if not inserted:
        raise RuntimeError("failed to create section")
    row = inserted[0]
    return DailyMenuSection(**row, items=[])


def update_section(section_id: str, body: UpdateDailyMenuSectionBody) -> None:
    patch = body.model_dump(exclude_none=True)
    if not patch:
        return
    supabase.update("daily_menu_sections", f"id=eq.{section_id}", patch)


def delete_section(section_id: str) -> None:
    supabase.delete("daily_menu_sections", f"id=eq.{section_id}")


# ── Items CRUD ────────────────────────────────────────────────────────────


def create_item(section_id: str, body: CreateDailyMenuItemBody) -> DailyMenuItem:
    data = body.model_dump(exclude_none=True)
    data["section_id"] = section_id
    inserted = supabase.insert("daily_menu_items", data, return_result=True)
    if not inserted:
        raise RuntimeError("failed to create item")
    return DailyMenuItem(**inserted[0])


def update_item(item_id: str, body: UpdateDailyMenuItemBody) -> None:
    patch = body.model_dump(exclude_none=True)
    if not patch:
        return
    supabase.update("daily_menu_items", f"id=eq.{item_id}", patch)


def delete_item(item_id: str) -> None:
    supabase.delete("daily_menu_items", f"id=eq.{item_id}")

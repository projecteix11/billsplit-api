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


# ── Ownership helpers ─────────────────────────────────────────────────────


def _assert_menu_owner(menu_id: str, tenant_id: str) -> None:
    rows = supabase.select("daily_menus", f"select=id&id=eq.{menu_id}&tenant_id=eq.{tenant_id}&limit=1")
    if not rows:
        raise ValueError(f"daily menu {menu_id} not found")


def _assert_section_owner(section_id: str, tenant_id: str) -> None:
    rows = supabase.select(
        "daily_menu_sections",
        f"select=id,menu:daily_menus(tenant_id)&id=eq.{section_id}&limit=1",
    )
    if not rows or rows[0].get("menu", {}).get("tenant_id") != tenant_id:
        raise ValueError(f"daily menu section {section_id} not found")


def _assert_item_owner_menu(item_id: str, tenant_id: str) -> None:
    rows = supabase.select(
        "daily_menu_items",
        f"select=id,section:daily_menu_sections(menu:daily_menus(tenant_id))&id=eq.{item_id}&limit=1",
    )
    if not rows or rows[0].get("section", {}).get("menu", {}).get("tenant_id") != tenant_id:
        raise ValueError(f"daily menu item {item_id} not found")


# ── Daily menus CRUD ──────────────────────────────────────────────────────


def get_daily_menus(tenant_id: str) -> list[DailyMenu]:
    """Active menus only (public / client)."""
    rows = supabase.select(
        "daily_menus",
        f"{_MENU_SELECT}&tenant_id=eq.{tenant_id}&is_active=eq.true",
    )
    return _hydrate_menus(rows)


def get_all_daily_menus(tenant_id: str) -> list[DailyMenu]:
    """All menus including inactive (management)."""
    rows = supabase.select(
        "daily_menus",
        f"{_MENU_SELECT}&tenant_id=eq.{tenant_id}",
    )
    return _hydrate_menus(rows)


def get_daily_menu_by_id(menu_id: str) -> DailyMenu | None:
    rows = supabase.select(
        "daily_menus",
        f"{_MENU_SELECT}&id=eq.{menu_id}&limit=1",
    )
    menus = _hydrate_menus(rows)
    return menus[0] if menus else None


def create_daily_menu(body: CreateDailyMenuBody, tenant_id: str) -> DailyMenu:
    data = body.model_dump(exclude_none=True)
    data["tenant_id"] = tenant_id
    inserted = supabase.insert("daily_menus", data, return_result=True)
    if not inserted:
        raise RuntimeError("failed to create daily menu")
    menu = get_daily_menu_by_id(inserted[0]["id"])
    if not menu:
        raise RuntimeError("failed to read created daily menu")
    return menu


def update_daily_menu(menu_id: str, body: UpdateDailyMenuBody, tenant_id: str) -> None:
    _assert_menu_owner(menu_id, tenant_id)
    patch = body.model_dump(exclude_none=True)
    if not patch:
        return
    supabase.update("daily_menus", f"id=eq.{menu_id}", patch)


def delete_daily_menu(menu_id: str, tenant_id: str) -> None:
    _assert_menu_owner(menu_id, tenant_id)
    supabase.delete("daily_menus", f"id=eq.{menu_id}")


# ── Sections CRUD ─────────────────────────────────────────────────────────


def create_section(menu_id: str, body: CreateDailyMenuSectionBody, tenant_id: str) -> DailyMenuSection:
    _assert_menu_owner(menu_id, tenant_id)
    data = body.model_dump(exclude_none=True)
    data["menu_id"] = menu_id
    inserted = supabase.insert("daily_menu_sections", data, return_result=True)
    if not inserted:
        raise RuntimeError("failed to create section")
    row = inserted[0]
    return DailyMenuSection(**row, items=[])


def update_section(section_id: str, body: UpdateDailyMenuSectionBody, tenant_id: str) -> None:
    _assert_section_owner(section_id, tenant_id)
    patch = body.model_dump(exclude_none=True)
    if not patch:
        return
    supabase.update("daily_menu_sections", f"id=eq.{section_id}", patch)


def delete_section(section_id: str, tenant_id: str) -> None:
    _assert_section_owner(section_id, tenant_id)
    supabase.delete("daily_menu_sections", f"id=eq.{section_id}")


# ── Items CRUD ────────────────────────────────────────────────────────────


def create_item(section_id: str, body: CreateDailyMenuItemBody, tenant_id: str) -> DailyMenuItem:
    _assert_section_owner(section_id, tenant_id)
    data = body.model_dump(exclude_none=True)
    data["section_id"] = section_id
    inserted = supabase.insert("daily_menu_items", data, return_result=True)
    if not inserted:
        raise RuntimeError("failed to create item")
    return DailyMenuItem(**inserted[0])


def update_item(item_id: str, body: UpdateDailyMenuItemBody, tenant_id: str) -> None:
    _assert_item_owner_menu(item_id, tenant_id)
    patch = body.model_dump(exclude_none=True)
    if not patch:
        return
    supabase.update("daily_menu_items", f"id=eq.{item_id}", patch)


def delete_item(item_id: str, tenant_id: str) -> None:
    _assert_item_owner_menu(item_id, tenant_id)
    supabase.delete("daily_menu_items", f"id=eq.{item_id}")

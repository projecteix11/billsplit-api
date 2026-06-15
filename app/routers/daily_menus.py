from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app.middleware.auth import require_auth
from app.middleware.rate_limit import limiter
from app.middleware.tenant import require_feature
from app.models import (
    CreateDailyMenuBody,
    CreateDailyMenuItemBody,
    CreateDailyMenuSectionBody,
    UpdateDailyMenuBody,
    UpdateDailyMenuItemBody,
    UpdateDailyMenuSectionBody,
)
from app.services import daily_menus as svc
from app.http_errors import internal_error

router = APIRouter()


# ── Daily menus ────────────────────────────────────────────────────────────


@router.get("/daily-menus")
async def get_daily_menus(all: bool = False, tenant_id: str = Depends(require_feature("daily_menus"))):
    try:
        if all:
            data = svc.get_all_daily_menus(tenant_id)
        else:
            data = svc.get_daily_menus(tenant_id)
        return {"data": [m.model_dump() for m in data], "error": None}
    except Exception as e:
        return internal_error(e)


@router.get("/daily-menus/{menu_id}")
def get_daily_menu(menu_id: str):
    try:
        menu = svc.get_daily_menu_by_id(menu_id)
        if menu is None:
            return JSONResponse(status_code=404, content={"data": None, "error": "Menu not found"})
        return {"data": menu.model_dump(), "error": None}
    except Exception as e:
        return internal_error(e)


@router.post("/daily-menus", status_code=201)
@limiter.limit("20/minute")
async def create_daily_menu(request: Request, body: CreateDailyMenuBody, _user_id: str = Depends(require_auth), tenant_id: str = Depends(require_feature("daily_menus"))):
    try:
        menu = svc.create_daily_menu(body, tenant_id)
        return JSONResponse(status_code=201, content={"data": menu.model_dump(), "error": None})
    except Exception as e:
        return internal_error(e)


@router.patch("/daily-menus/{menu_id}")
@limiter.limit("30/minute")
def update_daily_menu(request: Request, menu_id: str, body: UpdateDailyMenuBody, _user_id: str = Depends(require_auth), tenant_id: str = Depends(require_feature("daily_menus"))):
    try:
        svc.update_daily_menu(menu_id, body, tenant_id)
        menu = svc.get_daily_menu_by_id(menu_id)
        return {"data": menu.model_dump() if menu else None, "error": None}
    except ValueError:
        return JSONResponse(status_code=404, content={"data": None, "error": "Daily menu not found"})
    except Exception as e:
        return internal_error(e)


@router.delete("/daily-menus/{menu_id}")
@limiter.limit("20/minute")
def delete_daily_menu(request: Request, menu_id: str, _user_id: str = Depends(require_auth), tenant_id: str = Depends(require_feature("daily_menus"))):
    try:
        svc.delete_daily_menu(menu_id, tenant_id)
        return {"data": None, "error": None}
    except ValueError:
        return JSONResponse(status_code=404, content={"data": None, "error": "Daily menu not found"})
    except Exception as e:
        return internal_error(e)


# ── Sections ───────────────────────────────────────────────────────────────


@router.post("/daily-menus/{menu_id}/sections", status_code=201)
@limiter.limit("20/minute")
def create_section(request: Request, menu_id: str, body: CreateDailyMenuSectionBody, _user_id: str = Depends(require_auth), tenant_id: str = Depends(require_feature("daily_menus"))):
    try:
        section = svc.create_section(menu_id, body, tenant_id)
        return JSONResponse(status_code=201, content={"data": section.model_dump(), "error": None})
    except ValueError:
        return JSONResponse(status_code=404, content={"data": None, "error": "Daily menu not found"})
    except Exception as e:
        return internal_error(e)


@router.patch("/daily-menu-sections/{section_id}")
@limiter.limit("30/minute")
def update_section(request: Request, section_id: str, body: UpdateDailyMenuSectionBody, _user_id: str = Depends(require_auth), tenant_id: str = Depends(require_feature("daily_menus"))):
    try:
        svc.update_section(section_id, body, tenant_id)
        return {"data": None, "error": None}
    except ValueError:
        return JSONResponse(status_code=404, content={"data": None, "error": "Daily menu section not found"})
    except Exception as e:
        return internal_error(e)


@router.delete("/daily-menu-sections/{section_id}")
@limiter.limit("20/minute")
def delete_section(request: Request, section_id: str, _user_id: str = Depends(require_auth), tenant_id: str = Depends(require_feature("daily_menus"))):
    try:
        svc.delete_section(section_id, tenant_id)
        return {"data": None, "error": None}
    except ValueError:
        return JSONResponse(status_code=404, content={"data": None, "error": "Daily menu section not found"})
    except Exception as e:
        return internal_error(e)


# ── Items ──────────────────────────────────────────────────────────────────


@router.post("/daily-menu-sections/{section_id}/items", status_code=201)
@limiter.limit("20/minute")
def create_item(request: Request, section_id: str, body: CreateDailyMenuItemBody, _user_id: str = Depends(require_auth), tenant_id: str = Depends(require_feature("daily_menus"))):
    try:
        item = svc.create_item(section_id, body, tenant_id)
        return JSONResponse(status_code=201, content={"data": item.model_dump(), "error": None})
    except ValueError:
        return JSONResponse(status_code=404, content={"data": None, "error": "Daily menu section not found"})
    except Exception as e:
        return internal_error(e)


@router.patch("/daily-menu-items/{item_id}")
@limiter.limit("30/minute")
def update_item(request: Request, item_id: str, body: UpdateDailyMenuItemBody, _user_id: str = Depends(require_auth), tenant_id: str = Depends(require_feature("daily_menus"))):
    try:
        svc.update_item(item_id, body, tenant_id)
        return {"data": None, "error": None}
    except ValueError:
        return JSONResponse(status_code=404, content={"data": None, "error": "Daily menu item not found"})
    except Exception as e:
        return internal_error(e)


@router.delete("/daily-menu-items/{item_id}")
@limiter.limit("20/minute")
def delete_item(request: Request, item_id: str, _user_id: str = Depends(require_auth), tenant_id: str = Depends(require_feature("daily_menus"))):
    try:
        svc.delete_item(item_id, tenant_id)
        return {"data": None, "error": None}
    except ValueError:
        return JSONResponse(status_code=404, content={"data": None, "error": "Daily menu item not found"})
    except Exception as e:
        return internal_error(e)

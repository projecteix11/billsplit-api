from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.db import supabase

router = APIRouter()


@router.get("/tenants/by-slug/{slug}")
def get_tenant_by_slug(slug: str):
    try:
        rows = supabase.select(
            "tenants",
            f"select=id,name,slug,features,branding&slug=eq.{slug}&is_active=eq.true&limit=1",
        )
        if not rows:
            return JSONResponse(status_code=404, content={"data": None, "error": "Tenant not found"})
        return {"data": rows[0], "error": None}
    except Exception as e:
        return JSONResponse(status_code=500, content={"data": None, "error": str(e)})

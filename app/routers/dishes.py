from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.services import dishes as svc

router = APIRouter()


@router.get("/api/dishes")
def get_dishes():
    try:
        data = svc.get_dishes()
        return {"data": [d.model_dump() for d in data], "error": None}
    except Exception as e:
        return JSONResponse(status_code=500, content={"data": None, "error": str(e)})


@router.get("/api/categories")
def get_categories():
    try:
        data = svc.get_categories()
        return {"data": [c.model_dump() for c in data], "error": None}
    except Exception as e:
        return JSONResponse(status_code=500, content={"data": None, "error": str(e)})

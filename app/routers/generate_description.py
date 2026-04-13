from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.middleware.auth import require_auth
from app.middleware.rate_limit import limiter
from app.services import generate_description as gen_desc_svc

router = APIRouter()

MAX_DISH_NAME_LENGTH = 100


class GenerateDescriptionRequest(BaseModel):
    dish_name: str = Field(..., min_length=1, max_length=MAX_DISH_NAME_LENGTH)
    language: str = Field(default="es", pattern="^(es|en|ca)$")


@router.post("/api/generate-description")
@limiter.limit("10/minute")
def generate_description(
    request: Request,
    body: GenerateDescriptionRequest,
    _user_id: str = Depends(require_auth),
):
    result = gen_desc_svc.generate(
        dish_name=body.dish_name,
        language=body.language,
    )
    return JSONResponse(content={"data": result, "error": None})

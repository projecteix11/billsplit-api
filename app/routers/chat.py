import os
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.middleware.auth import require_auth
from app.middleware.rate_limit import limiter
from app.services import chat as chat_svc

router = APIRouter()

MAX_MESSAGE_LENGTH = 500
MAX_HISTORY_LENGTH = 50

VALID_MODEL_IDS = {m["id"] for m in chat_svc.AVAILABLE_MODELS}


class ConversationMessage(BaseModel):
    role: str = Field(..., pattern="^(user|assistant)$")
    content: str


class DeviceContext(BaseModel):
    printer_name: str | None = None
    printer_online: bool | None = None


class ChatRequest(BaseModel):
    message: str
    table_id: str | None = None
    order_id: str | None = None
    model: str | None = None
    features_kitchen: bool = False
    features_web: bool = False
    conversation_history: list[ConversationMessage] = []
    device_context: DeviceContext | None = None


@router.get("/chat/models")
def get_models(_user_id: str = Depends(require_auth)):
    return {
        "models": chat_svc.AVAILABLE_MODELS,
        "default": chat_svc.DEFAULT_MODEL,
    }


@router.get("/chat/balance")
def get_balance(_user_id: str = Depends(require_auth)):
    # Query DeepSeek balance using its API key
    key = os.getenv("DEEPSEEK_API_KEY", "")
    if not key:
        return {"is_available": False, "error": "No DeepSeek API key configured"}

    import httpx as http
    try:
        resp = http.get(
            "https://api.deepseek.com/user/balance",
            headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
            timeout=5
        )
        if resp.status_code == 200:
            return resp.json()
        return {"is_available": False, "error": f"API returned status {resp.status_code}"}
    except Exception as e:
        return {"is_available": False, "error": str(e)}


@router.post("/chat")
@limiter.limit("20/minute")
def chat(
    request: Request,
    body: ChatRequest,
    _user_id: str = Depends(require_auth),
):
    if len(body.message) > MAX_MESSAGE_LENGTH:
        return JSONResponse(
            status_code=400,
            content={"data": None, "error": f"Message exceeds {MAX_MESSAGE_LENGTH} characters"},
        )

    # Validate model if provided
    model = body.model
    if model and model not in VALID_MODEL_IDS:
        return JSONResponse(
            status_code=400,
            content={"data": None, "error": f"Unknown model: {model}"},
        )

    history = [{"role": m.role, "content": m.content} for m in body.conversation_history]
    if len(history) > MAX_HISTORY_LENGTH:
        history = history[-MAX_HISTORY_LENGTH:]

    tenant_id = getattr(request.state, "tenant_id", "")

    return StreamingResponse(
        chat_svc.stream_chat(
            message=body.message,
            conversation_history=history,
            table_id=body.table_id,
            order_id=body.order_id,
            model=model,
            features_kitchen=body.features_kitchen,
            features_web=body.features_web,
            device_context=body.device_context.model_dump() if body.device_context else None,
            tenant_id=tenant_id,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

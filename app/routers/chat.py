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


class ChatRequest(BaseModel):
    message: str
    table_id: str | None = None
    order_id: str | None = None
    model: str | None = None
    features_kitchen: bool = False
    features_web: bool = False
    conversation_history: list[ConversationMessage] = []


@router.get("/chat/models")
def get_models(_user_id: str = Depends(require_auth)):
    return {
        "models": chat_svc.AVAILABLE_MODELS,
        "default": chat_svc.DEFAULT_MODEL,
    }


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

    return StreamingResponse(
        chat_svc.stream_chat(
            message=body.message,
            conversation_history=history,
            table_id=body.table_id,
            order_id=body.order_id,
            model=model,
            features_kitchen=body.features_kitchen,
            features_web=body.features_web,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

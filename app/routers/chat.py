from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from app.middleware.auth import require_auth
from app.middleware.rate_limit import limiter
from app.services import chat as chat_svc

router = APIRouter()

MAX_MESSAGE_LENGTH = 500
MAX_HISTORY_LENGTH = 50


class ConversationMessage(BaseModel):
    role: str = Field(..., pattern="^(user|assistant)$")
    content: str


class ChatRequest(BaseModel):
    message: str
    table_id: str | None = None
    order_id: str | None = None
    conversation_history: list[ConversationMessage] = []


@router.post("/chat")
@limiter.limit("20/minute")
def chat(
    request: Request,
    body: ChatRequest,
    _user_id: str = Depends(require_auth),
):
    # Validate message length
    if len(body.message) > MAX_MESSAGE_LENGTH:
        return JSONResponse(
            status_code=400,
            content={"data": None, "error": f"Message exceeds {MAX_MESSAGE_LENGTH} characters"},
        )

    # Truncate conversation history (keep most recent)
    history = [{"role": m.role, "content": m.content} for m in body.conversation_history]
    if len(history) > MAX_HISTORY_LENGTH:
        history = history[-MAX_HISTORY_LENGTH:]

    return StreamingResponse(
        chat_svc.stream_chat(
            message=body.message,
            conversation_history=history,
            table_id=body.table_id,
            order_id=body.order_id,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

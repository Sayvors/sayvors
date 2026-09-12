import json
from typing import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.deps import get_db, get_current_user
from ..users.models import User
from .providers.base import ProviderError
from .schemas import (
    ChatRequest,
    ChatResponse,
    ConversationCreate,
    ConversationListResponse,
    ConversationResponse,
    MessageCreate,
    MessageListResponse,
    MessageResponse,
    ModelListResponse,
    ModelResponse,
)
from .service import (
    create_conversation,
    get_conversation,
    list_conversations,
    list_messages,
    send_message,
    stream_message,
)

router = APIRouter(prefix="/api/v1/llm", tags=["llm"])


# ── models catalog ──────────────────────────────────────


@router.get("/models", response_model=ModelListResponse)
async def get_models(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from .providers.registry import list_tenant_models

    # Tenants see exactly what the admin saved in the database —
    # never the code catalog. Every returned item is usable.
    items = [
        ModelResponse(
            id=m.id,
            name=m.name,
            provider=m.provider,
            context=m.context,
            max_output=m.max_output,
            supports_stream=m.supports_stream,
            available=True,
            key_source=source,
        )
        for m, source in await list_tenant_models(db)
    ]
    return ModelListResponse(models=items)


# ── conversations ───────────────────────────────────────


@router.post("/conversations", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
async def create_new_conversation(
    body: ConversationCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conv = await create_conversation(body, user, db)
    return ConversationResponse(
        id=conv.id,
        title=conv.title,
        model=conv.model,
        created_at=conv.created_at.isoformat(),
        updated_at=conv.updated_at.isoformat(),
    )


@router.get("/conversations", response_model=ConversationListResponse)
async def get_conversations(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    convs, total = await list_conversations(user, db, limit, offset)
    return ConversationListResponse(
        conversations=[
            ConversationResponse(
                id=c.id,
                title=c.title,
                model=c.model,
                created_at=c.created_at.isoformat(),
                updated_at=c.updated_at.isoformat(),
            )
            for c in convs
        ],
        total=total,
    )


@router.get("/conversations/{conv_id}", response_model=ConversationResponse)
async def get_conversation_by_id(
    conv_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conv = await get_conversation(conv_id, user, db)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return ConversationResponse(
        id=conv.id,
        title=conv.title,
        model=conv.model,
        created_at=conv.created_at.isoformat(),
        updated_at=conv.updated_at.isoformat(),
    )


# ── messages ────────────────────────────────────────────


@router.post(
    "/conversations/{conv_id}/messages",
    response_model=MessageResponse,
    status_code=status.HTTP_201_CREATED,
)
async def add_message(
    conv_id: str,
    body: MessageCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        user_msg, assistant_msg = await send_message(conv_id, body, user, db)
    except ValueError:
        raise HTTPException(status_code=404, detail="Conversation not found")
    except ProviderError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)
    return MessageResponse(
        id=assistant_msg.id,
        role=assistant_msg.role,
        content=assistant_msg.content,
        tokens=assistant_msg.tokens,
        created_at=assistant_msg.created_at.isoformat(),
    )


@router.get("/conversations/{conv_id}/messages", response_model=MessageListResponse)
async def get_messages(
    conv_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    msgs, total = await list_messages(conv_id, user, db, limit, offset)
    return MessageListResponse(
        messages=[
            MessageResponse(
                id=m.id,
                role=m.role,
                content=m.content,
                tokens=m.tokens,
                created_at=m.created_at.isoformat(),
            )
            for m in msgs
        ],
        total=total,
    )


# ── chat ────────────────────────────────────────────────


@router.post("/chat", response_model=ChatResponse)
async def chat(
    body: ChatRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Reuse existing conversation or create new one
    if body.conversation_id:
        conv = await get_conversation(body.conversation_id, user, db)
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")
    else:
        conv = await create_conversation(
            ConversationCreate(title=None, model=body.model, system_prompt=body.system_prompt),
            user,
            db,
        )
    try:
        user_msg, assistant_msg = await send_message(
            conv.id, MessageCreate(content=body.messages[-1].content), user, db
        )
    except ProviderError as e:
        raise HTTPException(status_code=e.status_code, detail=e.message)

    return ChatResponse(
        conversation_id=conv.id,
        message=MessageResponse(
            id=assistant_msg.id,
            role=assistant_msg.role,
            content=assistant_msg.content,
            tokens=assistant_msg.tokens,
            created_at=assistant_msg.created_at.isoformat(),
        ),
        usage={
            "prompt_tokens": 0,
            "completion_tokens": assistant_msg.tokens or 0,
            "total_tokens": assistant_msg.tokens or 0,
        },
    )


@router.post("/chat/stream")
async def chat_stream(
    body: ChatRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Reuse existing conversation or create new one
    if body.conversation_id:
        conv = await get_conversation(body.conversation_id, user, db)
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")
    else:
        conv = await create_conversation(
            ConversationCreate(title=None, model=body.model, system_prompt=body.system_prompt),
            user,
            db,
        )

    async def event_generator() -> AsyncIterator[str]:
        try:
            async for event in stream_message(
                conv.id,
                MessageCreate(content=body.messages[-1].content),
                user,
                db,
            ):
                yield f"data: {json.dumps(event)}\n\n"
        except ProviderError as e:
            yield f"data: {json.dumps({'type': 'error', 'message': e.message})}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

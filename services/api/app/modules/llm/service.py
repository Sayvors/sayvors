import uuid
from datetime import datetime, timezone

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..users.models import User
from .models import Conversation, Message
from .providers.base import LLMMessage, LLMRequest, ProviderError
from .providers.catalog import get_model_by_id, get_provider_from_model
from .providers.registry import get_provider_for_model
from .schemas import ChatRequest, ConversationCreate, MessageCreate
from ...database import async_session as _async_session

# Max messages to include in LLM context (token-aware windowing)
MAX_HISTORY_MESSAGES = 40


async def create_conversation(
    body: ConversationCreate, user: User, db: AsyncSession
) -> Conversation:
    conv = Conversation(
        id=str(uuid.uuid4()),
        user_id=user.id,
        title=body.title,
        model=body.model,
        system_prompt=body.system_prompt,
    )
    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    return conv


async def list_conversations(
    user: User, db: AsyncSession, limit: int = 20, offset: int = 0
) -> tuple[list[Conversation], int]:
    count_result = await db.execute(
        select(func.count()).where(Conversation.user_id == user.id)
    )
    total = count_result.scalar() or 0
    result = await db.execute(
        select(Conversation)
        .where(Conversation.user_id == user.id)
        .order_by(Conversation.updated_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all()), total


async def get_conversation(
    conv_id: str, user: User, db: AsyncSession
) -> Conversation | None:
    result = await db.execute(
        select(Conversation).where(
            Conversation.id == conv_id, Conversation.user_id == user.id
        )
    )
    return result.scalar_one_or_none()


async def list_messages(
    conv_id: str, user: User, db: AsyncSession, limit: int = 50, offset: int = 0
) -> tuple[list[Message], int]:
    conv = await get_conversation(conv_id, user, db)
    if not conv:
        return [], 0

    count_result = await db.execute(
        select(func.count()).where(Message.conversation_id == conv_id)
    )
    total = count_result.scalar() or 0
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conv_id)
        .order_by(Message.created_at)
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all()), total


async def _load_history(conv_id: str, db: AsyncSession) -> list[LLMMessage]:
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conv_id)
        .order_by(Message.created_at.desc())
        .limit(MAX_HISTORY_MESSAGES)
    )
    messages = list(reversed(result.scalars().all()))
    return [LLMMessage(role=m.role, content=m.content) for m in messages]


def _resolve_model(model_id: str) -> tuple[str, str]:
    from .providers.registry import get_effective_model

    info = get_effective_model(model_id) or get_model_by_id(model_id)
    if info:
        return info.api_model, info.provider
    provider = get_provider_from_model(model_id)
    parts = model_id.split(":", 1)
    api_model = parts[1] if len(parts) == 2 else model_id
    return api_model, provider


async def send_message(
    conv_id: str, body: MessageCreate, user: User, db: AsyncSession
) -> tuple[Message, Message]:
    conv = await get_conversation(conv_id, user, db)
    if not conv:
        raise ValueError("Conversation not found")

    user_msg = Message(
        id=str(uuid.uuid4()),
        conversation_id=conv_id,
        role="user",
        content=body.content,
    )
    db.add(user_msg)
    await db.flush()
    await db.commit()
    await db.close()

    async with _async_session() as read_db:
        history = await _load_history(conv_id, read_db)

    history.append(LLMMessage(role="user", content=body.content))

    api_model, provider_key = _resolve_model(conv.model)

    provider = get_provider_for_model(conv.model)
    req = LLMRequest(
        model=api_model,
        messages=history,
        system_prompt=conv.system_prompt,
        temperature=0.7,
        max_tokens=1000,
        stream=False,
        tenant_id=user.id,
        model_id=conv.model,
        purpose="chat.message",
    )

    try:
        resp = await provider.complete(req)
        content = resp.content
        tokens = resp.usage.total_tokens
        actual_model = resp.model
    except ProviderError:
        raise
    except Exception as e:
        raise ProviderError(provider_key, str(e), 502)

    async with _async_session() as write_db:
        assistant_msg = Message(
            id=str(uuid.uuid4()),
            conversation_id=conv_id,
            role="assistant",
            content=content,
            tokens=tokens,
            provider_model=actual_model,
        )
        write_db.add(assistant_msg)
        conv_db = await get_conversation(conv_id, user, write_db)
        if conv_db:
            conv_db.updated_at = datetime.now(timezone.utc)
        await write_db.commit()

    return user_msg, assistant_msg


async def stream_message(
    conv_id: str, body: MessageCreate, user: User, db: AsyncSession,
):
    conv = await get_conversation(conv_id, user, db)
    if not conv:
        raise ValueError("Conversation not found")

    user_msg = Message(
        id=str(uuid.uuid4()),
        conversation_id=conv_id,
        role="user",
        content=body.content,
    )
    db.add(user_msg)
    await db.flush()
    await db.commit()
    await db.close()

    async with _async_session() as read_db:
        history = await _load_history(conv_id, read_db)

    history.append(LLMMessage(role="user", content=body.content))

    api_model, provider_key = _resolve_model(conv.model)
    provider = get_provider_for_model(conv.model)

    req = LLMRequest(
        model=api_model,
        messages=history,
        system_prompt=conv.system_prompt,
        temperature=0.7,
        max_tokens=1000,
        stream=True,
    )

    full_content = []
    try:
        async for chunk in provider.stream(req):
            full_content.append(chunk)
            yield {"type": "token", "content": chunk}
    except ProviderError:
        raise
    except Exception as e:
        raise ProviderError(provider_key, str(e), 502)

    final_text = "".join(full_content)

    async with _async_session() as write_db:
        assistant_msg = Message(
            id=str(uuid.uuid4()),
            conversation_id=conv_id,
            role="assistant",
            content=final_text,
            provider_model=api_model,
        )
        write_db.add(assistant_msg)
        conv_db = await get_conversation(conv_id, user, write_db)
        if conv_db:
            conv_db.updated_at = datetime.now(timezone.utc)
        await write_db.commit()

    yield {
        "type": "done",
        "message_id": assistant_msg.id,
        "conversation_id": conv_id,
    }

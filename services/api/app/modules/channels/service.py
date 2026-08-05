import hashlib
import hmac
import json
import uuid
from datetime import datetime, timezone

from fastapi import Request
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from ..users.models import User
from .models import Channel, ChannelMessage
from .schemas import ChannelCreate, ChannelMessageSend


def _get_fernet():
    """Lazy-load Fernet for token encryption."""
    from cryptography.fernet import Fernet
    # Derive a Fernet key from JWT_SECRET (deterministic, same every boot)
    key = hashlib.sha256(settings.JWT_SECRET.encode()).digest()
    import base64
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt_token(token: str) -> str:
    """Encrypt an OAuth token at rest."""
    if not token:
        return token
    return _get_fernet().encrypt(token.encode()).decode()


def decrypt_token(encrypted: str) -> str:
    """Decrypt an OAuth token."""
    if not encrypted:
        return encrypted
    return _get_fernet().decrypt(encrypted.encode()).decode()


async def verify_webhook_signature(
    platform: str, payload: bytes, signature: str, channel: Channel
) -> bool:
    """Verify webhook signature for supported platforms."""
    secret = channel.webhook_secret
    if not secret:
        return False

    if platform == "telegram":
        # Telegram: HMAC-SHA256
        expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)
    elif platform == "whatsapp":
        # WhatsApp: HMAC-SHA256
        expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)
    elif platform in ("facebook", "instagram"):
        # Meta: HMAC-SHA256 with app secret
        expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)
    elif platform == "x":
        # X/Twitter: HMAC-SHA256
        expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    return False


async def create_channel(body: ChannelCreate, user: User, db: AsyncSession) -> Channel:
    channel = Channel(
        id=str(uuid.uuid4()),
        user_id=user.id,
        platform=body.platform,
        platform_user_id=body.platform_user_id,
        display_name=body.display_name,
        access_token=encrypt_token(body.access_token) if body.access_token else None,
    )
    db.add(channel)
    await db.commit()
    await db.refresh(channel)
    return channel


async def list_channels(
    user: User, db: AsyncSession, limit: int = 20, offset: int = 0
) -> tuple[list[Channel], int]:
    count_result = await db.execute(
        select(func.count()).where(Channel.user_id == user.id)
    )
    total = count_result.scalar() or 0
    result = await db.execute(
        select(Channel)
        .where(Channel.user_id == user.id)
        .order_by(Channel.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all()), total


async def get_channel(
    channel_id: str, user: User, db: AsyncSession
) -> Channel | None:
    result = await db.execute(
        select(Channel).where(Channel.id == channel_id, Channel.user_id == user.id)
    )
    return result.scalar_one_or_none()


async def delete_channel(channel_id: str, user: User, db: AsyncSession) -> bool:
    channel = await get_channel(channel_id, user, db)
    if not channel:
        return False
    await db.delete(channel)
    await db.commit()
    return True


async def send_message(
    channel_id: str, body: ChannelMessageSend, user: User, db: AsyncSession
) -> ChannelMessage:
    channel = await get_channel(channel_id, user, db)
    if not channel:
        raise ValueError("Channel not found")

    msg = ChannelMessage(
        id=str(uuid.uuid4()),
        channel_id=channel_id,
        direction="outbound",
        content=body.content,
        content_type=body.content_type,
        status="sent",
    )
    db.add(msg)

    # TODO: dispatch to platform API (Facebook Graph, Instagram, X API, etc.)
    # For now, mark as sent
    await db.commit()
    await db.refresh(msg)
    return msg


async def list_messages(
    channel_id: str, user: User, db: AsyncSession, limit: int = 50, offset: int = 0
) -> tuple[list[ChannelMessage], int]:
    channel = await get_channel(channel_id, user, db)
    if not channel:
        return [], 0

    count_result = await db.execute(
        select(func.count()).where(ChannelMessage.channel_id == channel_id)
    )
    total = count_result.scalar() or 0
    result = await db.execute(
        select(ChannelMessage)
        .where(ChannelMessage.channel_id == channel_id)
        .order_by(ChannelMessage.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all()), total


async def handle_webhook(
    platform: str, payload: dict, db: AsyncSession
) -> ChannelMessage | None:
    # TODO: verify webhook signature, parse platform-specific payload
    # For now, return None — will be wired up per platform
    return None

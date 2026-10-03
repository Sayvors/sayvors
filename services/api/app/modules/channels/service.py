import functools
import hashlib
import hmac
import json
import uuid
from datetime import datetime, timezone

from fastapi import Request
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...config import settings
from ..users.models import User
from .models import Channel, ChannelMessage
from .schemas import ChannelCreate, ChannelMessageSend


@functools.lru_cache(maxsize=1)
def _get_fernet():
    """Lazy-load Fernet for token encryption (derived once per process).

    Primary key: CHANNEL_ENCRYPTION_KEY (dedicated, independent of the JWT
    signing secret — leaking one must not unlock the other). When unset, the
    legacy JWT-derived key is used so existing deployments keep working, and
    a loud log tells operators to set the dedicated key.

    Decryption tries the primary key first, then falls back to legacy, so
    setting CHANNEL_ENCRYPTION_KEY later never breaks previously stored
    ciphertext. New writes always use the primary key.
    """
    import base64
    import logging

    from cryptography.fernet import Fernet, InvalidToken

    log = logging.getLogger(__name__)

    def _fernet_from(secret: str):
        key = hashlib.sha256(secret.encode()).digest()
        return Fernet(base64.urlsafe_b64encode(key))

    primary_secret = (settings.CHANNEL_ENCRYPTION_KEY or "").strip()
    legacy_fernet = _fernet_from(settings.JWT_SECRET)

    if primary_secret:
        class _PrimaryFirstFernet:
            def encrypt(self, data: bytes) -> bytes:
                return _fernet_from(primary_secret).encrypt(data)

            def decrypt(self, token: bytes) -> bytes:
                try:
                    return _fernet_from(primary_secret).decrypt(token)
                except InvalidToken:
                    return legacy_fernet.decrypt(token)

        return _PrimaryFirstFernet()

    log.warning(
        "CHANNEL_ENCRYPTION_KEY is not set — credential encryption is falling "
        "back to a key derived from JWT_SECRET. Set a dedicated "
        "CHANNEL_ENCRYPTION_KEY so JWT and storage keys are independent."
    )

    class _LegacyFernet:
        def encrypt(self, data: bytes) -> bytes:
            return legacy_fernet.encrypt(data)

        def decrypt(self, data: bytes) -> bytes:
            return legacy_fernet.decrypt(data)

    return _LegacyFernet()


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
    import json as _json

    from sqlalchemy.exc import IntegrityError

    metadata: dict = {}
    if body.location_id:
        metadata["location_id"] = body.location_id

    key = channel_listing_key(body.platform, metadata)
    channel = Channel(
        id=str(uuid.uuid4()),
        user_id=user.id,
        platform=body.platform,
        platform_user_id=body.platform_user_id or "",
        display_name=body.display_name,
        access_token=encrypt_token(body.access_token) if body.access_token else None,
        refresh_token=encrypt_token(body.refresh_token) if body.refresh_token else None,
        webhook_secret=body.webhook_secret or None,
        metadata_json=_json.dumps(metadata) if metadata else None,
        listing_key=key,
    )
    db.add(channel)
    try:
        await db.commit()
    except IntegrityError:
        # Lost a race (or double-clicked): the row already exists.
        await db.rollback()
        raise ValueError("Channel already connected")
    await db.refresh(channel)
    return channel


def parse_channel_metadata(metadata_json: str | None) -> dict:
    """metadata_json parsed safely (never raises — {} on garbage)."""
    if not metadata_json:
        return {}
    try:
        meta = json.loads(metadata_json)
    except (ValueError, TypeError):
        return {}
    return meta if isinstance(meta, dict) else {}


def channel_listing_key(platform: str, metadata: dict) -> str | None:
    """Stable per-location identity for google_reviews channels.

    Localith-mirrored rows carry listing_id; native OAuth rows carry
    location_id. Different ID spaces, so the two sources never collide.
    None for channels with no location identity (never deduped).
    """
    if not isinstance(metadata, dict):
        return None
    if platform == "google_reviews":
        key = metadata.get("listing_id") or metadata.get("location_id")
        return str(key) if key else None
    return None


async def find_channel_by_key(
    db: AsyncSession, user_id: str, platform: str, listing_key: str
) -> Channel | None:
    """Indexed lookup of one location's channel (the get in get-or-create)."""
    result = await db.execute(
        select(Channel).where(
            Channel.user_id == user_id,
            Channel.platform == platform,
            Channel.listing_key == listing_key,
        )
    )
    return result.scalar_one_or_none()


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
    """Send a message to a contact and record the result.

    The row is written with the outcome, never optimistically: a message that
    WhatsApp rejected must not read as "sent" in the inbox. Meta's 24-hour
    customer-service window is enforced by Meta, not here, so an out-of-window
    send comes back as a failed row carrying Meta's own error text.
    """
    channel = await get_channel(channel_id, user, db)
    if not channel:
        raise ValueError("Channel not found")

    contact_phone = (body.contact_phone or "").strip()
    if not contact_phone:
        raise ValueError("A recipient phone number is required to send")

    outbound = ChannelMessage(
        id=str(uuid.uuid4()),
        channel_id=channel_id,
        direction="outbound",
        content=body.content,
        content_type=body.content_type,
        status="sent",
        contact_phone=contact_phone,
        contact_name=body.contact_name or None,
    )

    try:
        provider_msg_id, error = await _dispatch_whatsapp(
            db, user, channel, contact_phone, body.content
        )
    except Exception as exc:  # noqa: BLE001 - recorded on the row, not raised
        provider_msg_id, error = "", str(exc)[:500]

    if error:
        outbound.status = "failed"
        outbound.error = error
    else:
        outbound.platform_message_id = provider_msg_id[:200] or None
        outbound.status = "sent"

    db.add(outbound)
    await db.commit()
    await db.refresh(outbound)
    return outbound


async def _dispatch_whatsapp(
    db: AsyncSession,
    user: User,
    channel: Channel,
    to: str,
    text: str,
) -> tuple[str, str]:
    """(provider_message_id, error). Exactly one of the two is meaningful.

    Ownership is re-resolved from the database rather than trusted from the
    channel row, mirroring the consumer: a channel must belong to this tenant
    before we use its credentials.
    """
    from .meta.credentials import decrypt_connection_token
    from .meta.models import MetaAsset
    from .meta.providers.base import MetaAPIError
    from .meta.providers.whatsapp import WhatsAppAdapter

    phone_number_id = channel.platform_user_id
    if not phone_number_id:
        return "", "This channel has no WhatsApp number attached."

    result = await db.execute(
        select(MetaAsset)
        .where(
            MetaAsset.tenant_id == user.id,
            MetaAsset.provider == "whatsapp",
            MetaAsset.external_asset_id == phone_number_id,
        )
        .options(selectinload(MetaAsset.connection))
    )
    asset = result.scalar_one_or_none()
    if asset is None:
        return "", "No WhatsApp account is connected for this number."
    if not asset.active:
        return "", "This WhatsApp number is not active."

    token = decrypt_connection_token(asset.connection) if asset.connection else None
    if not token:
        return "", "WhatsApp credentials are missing. Reconnect the account."

    try:
        provider_msg_id = await WhatsAppAdapter().send_text_message(
            phone_number_id, token, to, text
        )
    except MetaAPIError as exc:
        detail = f"{exc.status_code}: {exc}" if exc.status_code else str(exc)
        return "", detail[:500]
    if not provider_msg_id:
        return "", "WhatsApp accepted the request but returned no message id."
    return provider_msg_id, ""


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


# --- inbox: per-customer threads ------------------------------------------
#
# A channel is a phone number serving many customers, so the inbox cannot be a
# flat message list. Threads are derived at read time by grouping on
# (channel_id, contact_phone) rather than stored: there is no per-thread state
# worth its own table, and a new inbound message should never need to
# back-fill anything.

UNKNOWN_THREAD_KEY = "unknown"


def thread_key(contact_phone: str | None) -> str:
    return contact_phone or UNKNOWN_THREAD_KEY


async def list_inbox_threads(
    user: User,
    db: AsyncSession,
    search: str | None = None,
    limit: int = 100,
) -> list[dict]:
    """Threads across every channel the user owns, newest activity first.

    Built in SQL rather than by loading messages and grouping in Python: a
    busy inbox can hold tens of thousands of rows, and the aggregate here
    (last message, count, unread) is exactly what the database is for.
    """
    channels = (
        (
            await db.execute(select(Channel).where(Channel.user_id == user.id))
        )
        .scalars()
        .all()
    )
    if not channels:
        return []
    channel_ids = [c.id for c in channels]
    by_id = {c.id: c for c in channels}

    needle = f"%{search.strip()}%" if search and search.strip() else None
    stmt = (
        select(
            ChannelMessage.contact_phone,
            ChannelMessage.channel_id,
            func.max(ChannelMessage.created_at).label("last_at"),
            func.count(ChannelMessage.id).label("total"),
        )
        .where(ChannelMessage.channel_id.in_(channel_ids))
        .group_by(ChannelMessage.contact_phone, ChannelMessage.channel_id)
    )
    if needle:
        # Match the text of any message in the group, not the name: the contact
        # name is usually missing, and the phone is rarely what someone types.
        # HAVING, not WHERE — a filter here would drop whole threads instead of
        # narrowing them to matching messages.
        #
        # MAX(CASE ...) rather than bool_or: the two are equivalent here, but
        # bool_or does not exist in SQLite, which the test suite runs on.
        matched = func.max(
            case((ChannelMessage.content.ilike(needle), 1), else_=0)
        )
        stmt = stmt.having(matched == 1)
    stmt = stmt.order_by(func.max(ChannelMessage.created_at).desc()).limit(limit)

    summaries = (await db.execute(stmt)).all()
    if not summaries:
        return []

    # The preview line and unread count need per-thread detail the grouped
    # aggregate cannot carry, so fetch those rows only.
    out: list[dict] = []
    for phone, channel_id, last_at, total in summaries:
        conditions = [
            ChannelMessage.channel_id == channel_id,
            ChannelMessage.contact_phone.is_(None)
            if phone is None
            else ChannelMessage.contact_phone == phone,
        ]
        last_row = (
            await db.execute(
                select(ChannelMessage)
                .where(*conditions)
                .order_by(ChannelMessage.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if last_row is None:
            continue

        # Unread = inbound messages after the most recent outbound one.
        last_outbound_at = (
            await db.execute(
                select(func.max(ChannelMessage.created_at)).where(
                    *conditions,
                    ChannelMessage.direction == "outbound",
                )
            )
        ).scalar()
        unread = (
            await db.execute(
                select(func.count(ChannelMessage.id)).where(
                    *conditions,
                    ChannelMessage.direction == "inbound",
                    ChannelMessage.created_at > (last_outbound_at or last_at),
                )
            )
        ).scalar()
        if not last_outbound_at:
            unread = total if phone is not None else 0

        name = last_row.contact_name
        out.append(
            {
                "key": thread_key(phone),
                "contact_phone": phone,
                "display_name": name or phone,
                "channel_id": channel_id,
                "channel_name": by_id[channel_id].display_name,
                "platform": by_id[channel_id].platform,
                "last_message": (last_row.content or "")[:280],
                "last_message_at": last_at.isoformat() if last_at else None,
                "last_direction": last_row.direction,
                "message_count": total,
                "unread": int(unread or 0),
                "is_unknown": phone is None,
            }
        )
    return out


async def list_thread_messages(
    user: User,
    db: AsyncSession,
    channel_id: str,
    contact_phone: str | None,
    limit: int = 200,
) -> list[ChannelMessage]:
    """Every message in one thread, oldest first for display."""
    channel = await get_channel(channel_id, user, db)
    if not channel:
        return []
    conditions = [
        ChannelMessage.channel_id == channel_id,
        ChannelMessage.contact_phone.is_(None)
        if contact_phone is None
        else ChannelMessage.contact_phone == contact_phone,
    ]
    result = await db.execute(
        select(ChannelMessage)
        .where(*conditions)
        .order_by(ChannelMessage.created_at.desc())
        .limit(limit)
    )
    rows = list(result.scalars().all())
    return list(reversed(rows))

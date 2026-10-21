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
from ..team.context import tenant_id_of
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


def encrypt_message_content(content: str | None) -> str | None:
    """Encrypt a customer message body at rest."""
    if not content:
        return content
    return _get_fernet().encrypt(content.encode()).decode()


def decrypt_message_content(encrypted: str | None) -> str | None:
    """Decrypt a customer message body at rest.

    Gracefully returns the input as-is if it is not valid Fernet ciphertext
    (e.g. legacy plaintext rows or test fixtures). Production data is always
    encrypted; this fallback exists only for migration safety.
    """
    if not encrypted:
        return encrypted
    try:
        return _get_fernet().decrypt(encrypted.encode()).decode()
    except Exception:
        return encrypted


def encrypt_contact_phone(phone: str | None) -> str | None:
    """Encrypt a customer phone number at rest (PII)."""
    if not phone:
        return phone
    return _get_fernet().encrypt(phone.encode()).decode()


def decrypt_contact_phone(phone: str | None) -> str | None:
    """Decrypt a customer phone number at rest.

    Gracefully returns the input as-is if it is not valid Fernet ciphertext
    (e.g. legacy plaintext rows or test fixtures). Production data is always
    encrypted; this fallback exists only for migration safety.
    """
    if not phone:
        return phone
    try:
        return _get_fernet().decrypt(phone.encode()).decode()
    except Exception:
        return phone


# The levels a conversation can carry, most urgent first. ONE scale for
# every source, so a filter means the same thing wherever the
# conversation came from.
PRIORITY_LEVELS = ("urgent", "high", "normal", "low")

# A conversation is important when it needs a human now. The rule spans
# every source: an urgent or high priority, OR a complaint — which is
# what a one- or two-star Google review and a "my order never arrived"
# message both are. The Leads board's "important" is a different thing
# (an AI-missed thread); this one is about the conversation's content.
IMPORTANT_PRIORITIES = frozenset({"urgent", "high"})


def is_important(priority: str | None, category: str | None) -> bool:
    """Whether a conversation needs a human's attention now.

    Deliberately derived rather than stored: "important" is a question
    about the conversation, and storing the answer would mean three
    writers keeping it in step with the priority and category they also
    write.
    """
    if (priority or "normal").strip().lower() in IMPORTANT_PRIORITIES:
        return True
    return (category or "").strip().lower() == "complaint"


def categorize_message(
    content: str | None,
    platform: str | None = None,
    rating: int | None = None,
) -> tuple[str, str]:
    """Auto-categorise an inbound message into (category, priority).

    Rules (in priority order):
      - Google reviews, by rating: 1 star -> urgent, 2 -> high,
        3 -> normal, 4-5 -> low. A rating is the one honest signal a
        public review carries, and it is mapped onto the SAME scale the
        chat path uses so one rule can rank both.
      - Messages containing complaint keywords -> complaint, high
      - Messages containing urgent keywords -> important, urgent
      - Default -> normal, normal
    """
    text = (content or "").lower()
    plat = (platform or "").lower()

    # Google review: categorise by rating.
    if plat == "google_reviews" and rating is not None:
        if rating <= 1:
            return "complaint", "urgent"
        if rating == 2:
            return "complaint", "high"
        if rating == 3:
            return "feedback", "normal"
        return "feedback", "low"

    # Keyword-based heuristics for chat messages.
    complaint_words = {
        "complaint", "issue", "problem", "broken", "not working",
        "angry", "terrible", "worst", "refund", "cancel", "disappointed",
        "unhappy", "frustrated", "horrible", "awful", "scam", "fake",
    }
    urgent_words = {
        "urgent", "emergency", "asap", "immediately", "critical",
        "help", "sos", "911", "danger",
    }

    words = set(text.split())
    if complaint_words & words:
        return "complaint", "high"
    if urgent_words & words:
        return "important", "urgent"

    return "normal", "normal"


def encrypt_webhook_secret(secret: str | None) -> str | None:
    """Encrypt a channel webhook secret at rest."""
    if not secret:
        return secret
    return _get_fernet().encrypt(secret.encode()).decode()


def decrypt_webhook_secret(secret: str | None) -> str | None:
    """Decrypt a channel webhook secret at rest."""
    if not secret:
        return secret
    return _get_fernet().decrypt(secret.encode()).decode()


def hash_contact_phone(phone: str) -> str:
    """Hash a phone number for lookup without encryption.

    Uses HMAC-SHA256 with CHANNEL_ENCRYPTION_KEY as the key so the same phone
    always hashes to the same value, enabling lookups while keeping the
    plaintext phone encrypted at rest.
    """
    import hmac
    key = settings.CHANNEL_ENCRYPTION_KEY or settings.JWT_SECRET
    return hmac.new(key.encode(), phone.encode(), hashlib.sha256).hexdigest()


async def verify_webhook_signature(
    platform: str, payload: bytes, signature: str, channel: Channel
) -> bool:
    """Verify webhook signature for supported platforms."""
    secret = decrypt_webhook_secret(channel.webhook_secret)
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
        user_id=tenant_id_of(user),
        platform=body.platform,
        platform_user_id=body.platform_user_id or "",
        display_name=body.display_name,
        access_token=encrypt_token(body.access_token) if body.access_token else None,
        refresh_token=encrypt_token(body.refresh_token) if body.refresh_token else None,
        webhook_secret=encrypt_webhook_secret(body.webhook_secret) if body.webhook_secret else None,
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


def channel_location_ids(channel: Channel) -> set[str]:
    """Every id that identifies one Google location of this channel.

    A branch can be identified by its Localith listing id, its Google
    location id, or both (a Localith branch that was later connected
    through Google's own OAuth). Publishing resolves the channel from
    whichever id the client holds, so all of them are accepted.
    """
    ids: set[str] = set()
    try:
        import json as _json

        meta = _json.loads(channel.metadata_json or "{}")
    except (ValueError, TypeError):
        meta = {}
    if isinstance(meta, dict):
        for key in ("location_id", "listing_id"):
            value = meta.get(key)
            if value:
                ids.add(str(value))
    if channel.listing_key:
        ids.add(str(channel.listing_key))
    return ids


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
        select(func.count()).where(Channel.user_id == tenant_id_of(user))
    )
    total = count_result.scalar() or 0
    result = await db.execute(
        select(Channel)
        .where(Channel.user_id == tenant_id_of(user))
        .order_by(Channel.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all()), total


async def get_channel(
    channel_id: str, user: User, db: AsyncSession
) -> Channel | None:
    result = await db.execute(
        select(Channel).where(Channel.id == channel_id, Channel.user_id == tenant_id_of(user))
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

    The row is written with the outcome, never optimistically: a message the
    provider rejected must not read as "sent" in the inbox. Meta's 24-hour
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
        content=encrypt_message_content(body.content),
        content_type=body.content_type,
        status="sent",
        contact_phone=encrypt_contact_phone(contact_phone),
        contact_phone_hash=hash_contact_phone(contact_phone),
        contact_name=body.contact_name or None,
    )

    try:
        if channel.platform == "instagram":
            provider_msg_id, error = await _dispatch_instagram(
                db, user, channel, contact_phone, body.content
            )
        else:
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
            MetaAsset.tenant_id == tenant_id_of(user),
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


async def _dispatch_instagram(
    db: AsyncSession,
    user: User,
    channel: Channel,
    to: str,
    text: str,
) -> tuple[str, str]:
    """(provider_message_id, error) for Instagram DMs. `to` is the
    customer's IGSID.

    Sends ride the parent Facebook Page's token — the IG connection holds a
    user token, useless for messaging — so unlike the WhatsApp path there is
    no connection-token decryption here, just the parent asset lookup.
    """
    from .meta.models import MetaAsset
    from .meta.providers.base import MetaAPIError
    from .meta.providers.instagram import InstagramAdapter
    from .meta.service import get_instagram_page_credentials

    ig_account_id = channel.platform_user_id
    if not ig_account_id:
        return "", "This channel has no Instagram account attached."

    result = await db.execute(
        select(MetaAsset).where(
            MetaAsset.tenant_id == tenant_id_of(user),
            MetaAsset.provider == "instagram",
            MetaAsset.external_asset_id == ig_account_id,
        )
    )
    asset = result.scalar_one_or_none()
    if asset is None:
        return "", "No Instagram account is connected for this channel."
    if not asset.active:
        return "", "This Instagram account is not active."

    page_id, page_token = await get_instagram_page_credentials(db, asset)
    if not page_id or not page_token:
        return (
            "",
            "The Facebook Page linked to this Instagram account has no page "
            "token. Reconnect Instagram.",
        )

    try:
        provider_msg_id = await InstagramAdapter().send_text_message(
            page_id, page_token, to, text
        )
    except MetaAPIError as exc:
        detail = f"{exc.status_code}: {exc}" if exc.status_code else str(exc)
        return "", detail[:500]
    if not provider_msg_id:
        return "", "Instagram accepted the request but returned no message id."
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
    cursor: str | None = None,
) -> list[dict]:
    """Threads across every channel the user owns, newest activity first.

    Built in SQL rather than by loading messages and grouping in Python: a
    busy inbox can hold tens of thousands of rows, and the aggregate here
    (last message, count, unread) is exactly what the database is for.
    """
    # A disconnected channel is not reachable (Meta revoked / user
    # disconnected), so its threads stay out of the list — the history is
    # preserved and reappears when the same number reconnects. The status flag
    # only exists since the disconnect started writing it, so channels
    # disconnected before that are caught by their deactivated Meta asset —
    # every disconnect path deactivates the asset too.
    channels = (
        (
            await db.execute(select(Channel).where(Channel.user_id == tenant_id_of(user)))
        )
        .scalars()
        .all()
    )
    if not channels:
        return []
    from .meta.models import MetaAsset

    inactive_assets = {
        (provider, external)
        for provider, external in (
            await db.execute(
                select(MetaAsset.provider, MetaAsset.external_asset_id).where(
                    MetaAsset.tenant_id == tenant_id_of(user),
                    MetaAsset.active.is_(False),
                )
            )
        ).all()
    }
    channels = [
        c
        for c in channels
        if c.status != "disconnected"
        and (c.platform, c.platform_user_id) not in inactive_assets
    ]
    if not channels:
        return []
    channel_ids = [c.id for c in channels]
    by_id = {c.id: c for c in channels}

    needle = search.strip().lower() if search and search.strip() else None
    stmt = (
        select(
            ChannelMessage.contact_phone_hash,
            func.max(ChannelMessage.contact_phone).label("contact_phone"),
            ChannelMessage.channel_id,
            func.max(ChannelMessage.created_at).label("last_at"),
            func.count(ChannelMessage.id).label("total"),
        )
        .where(ChannelMessage.channel_id.in_(channel_ids))
        .group_by(ChannelMessage.contact_phone_hash, ChannelMessage.channel_id)
    )
    if cursor:
        try:
            cursor_dt = datetime.fromisoformat(cursor)
            if cursor_dt.tzinfo is None:
                cursor_dt = cursor_dt.replace(tzinfo=timezone.utc)
            stmt = stmt.having(func.max(ChannelMessage.created_at) < cursor_dt)
        except (ValueError, TypeError):
            pass
    stmt = stmt.order_by(func.max(ChannelMessage.created_at).desc()).limit(limit)

    summaries = (await db.execute(stmt)).all()
    if not summaries:
        return []

    # Batch fetch ALL messages for these channels in one query instead of
    # N per-thread queries. Group in Python — eliminates N+1.
    all_msgs = (
        await db.execute(
            select(ChannelMessage)
            .where(ChannelMessage.channel_id.in_(channel_ids))
            .order_by(ChannelMessage.created_at.desc())
        )
    ).scalars().all()

    # Index messages by (channel_id, contact_phone_hash) for fast lookup
    msgs_by_thread: dict[tuple, list] = {}
    for m in all_msgs:
        key = (m.channel_id, m.contact_phone_hash)
        msgs_by_thread.setdefault(key, []).append(m)

    # When searching, filter threads by decrypting message content in Python.
    # SQL ILIKE cannot match encrypted content.
    if needle:
        filtered_summaries = []
        for phone_hash, phone, channel_id, last_at, total in summaries:
            msgs = msgs_by_thread.get((channel_id, phone_hash), [])
            if any(needle in (decrypt_message_content(m.content) or "").lower() for m in msgs):
                filtered_summaries.append((phone_hash, phone, channel_id, last_at, total))
        summaries = filtered_summaries
        if not summaries:
            return []

    # Cached contact profiles (names/usernames/avatars) in one read — the
    # map lookup stays exact per (platform, contact) even though the IN
    # filters can over-fetch.
    from .models import ContactProfile

    profile_keys = {
        (by_id[cid].platform, decrypt_contact_phone(phone))
        for phone_hash, phone, cid, _la, _t in summaries
        if phone is not None
    }
    profiles: dict = {}
    if profile_keys:
        rows = (
            await db.execute(
                select(ContactProfile).where(
                    ContactProfile.tenant_id == tenant_id_of(user),
                    ContactProfile.platform.in_({p for p, _ in profile_keys}),
                    ContactProfile.contact_id.in_({c for _, c in profile_keys}),
                )
            )
        ).scalars().all()
        profiles = {(r.platform, r.contact_id): r for r in rows}

    # Build output from batched data — no per-thread queries.
    out: list[dict] = []
    for phone_hash, phone, channel_id, last_at, total in summaries:
        msgs = msgs_by_thread.get((channel_id, phone_hash), [])
        if not msgs:
            continue

        last_row = msgs[0]  # already sorted by created_at desc

        # Unread = inbound messages after the most recent outbound one.
        last_outbound_at = None
        for m in msgs:
            if m.direction == "outbound":
                last_outbound_at = m.created_at
                break
        unread = 0
        if last_outbound_at:
            unread = sum(1 for m in msgs if m.direction == "inbound" and m.created_at > last_outbound_at)
        else:
            unread = total if phone is not None else 0

        name = last_row.contact_name
        profile = (
            profiles.get((by_id[channel_id].platform, decrypt_contact_phone(phone)))
            if phone is not None
            else None
        )
        if profile is not None and profile.name:
            name = profile.name
        decrypted_phone = decrypt_contact_phone(phone) if phone is not None else None
        decrypted_last = decrypt_message_content(last_row.content) if last_row.content else ""
        category = last_row.category or "normal"
        priority = last_row.priority or "normal"
        platform = by_id[channel_id].platform
        out.append(
            {
                "key": thread_key(decrypted_phone),
                "contact_phone": decrypted_phone,
                "display_name": name or decrypted_phone,
                "username": profile.username if profile else None,
                "avatar_url": profile.avatar_url if profile else None,
                "channel_id": channel_id,
                "channel_name": by_id[channel_id].display_name,
                "platform": platform,
                "last_message": (decrypted_last or "")[:280],
                "last_message_at": last_at.isoformat() if last_at else None,
                "last_direction": last_row.direction,
                "message_count": total,
                "unread": int(unread or 0),
                "is_unknown": phone is None,
                "category": category,
                "priority": priority,
                # One rule, every source: an urgent/high conversation or
                # a complaint needs a human now.
                "important": is_important(priority, category),
                # A Google review is a public post, not a message — it is
                # answered through the review-reply flow, so the inbox's
                # send box must not offer to reply to it.
                "can_reply": platform != "google_reviews" and phone is not None,
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
        ChannelMessage.contact_phone_hash.is_(None)
        if contact_phone is None
        else ChannelMessage.contact_phone_hash
        == hash_contact_phone(contact_phone),
    ]
    result = await db.execute(
        select(ChannelMessage)
        .where(*conditions)
        .order_by(ChannelMessage.created_at.desc())
        .limit(limit)
    )
    rows = list(result.scalars().all())
    return list(reversed(rows))

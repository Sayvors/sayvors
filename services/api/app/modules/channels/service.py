import hashlib
import hmac
import json
import logging
import uuid
from datetime import datetime, timezone

from fastapi import Request
from sqlalchemy import case, func, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ...config import settings
from ...core.crypto import decrypt_secret as _decrypt_secret
from ...core.crypto import encrypt_secret as _encrypt_secret
from ...core.crypto import get_fernet as _get_fernet
from ..team.context import tenant_id_of
from ..users.models import User
from .models import Channel, ChannelMessage, ChannelThread, ContactProfile, Lead
from . import thread_maintenance  # noqa: F401  registers event listeners
from .schemas import ChannelCreate, ChannelMessageSend

logger = logging.getLogger(__name__)


def encrypt_token(token: str) -> str:
    """Encrypt an OAuth token at rest."""
    return _encrypt_secret(token)


def decrypt_token(encrypted: str) -> str:
    """Decrypt an OAuth token."""
    return _decrypt_secret(encrypted)


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
        handled_by="human",
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

    # Any human outbound means a person owns this conversation: mute the AI,
    # cancel any queued AI follow-up, and reset the escalation clock so the
    # next customer message is not treated as an AI miss. A failed send is
    # excluded on purpose — the customer never saw a human reply, so the AI
    # must keep answering.
    if not error:
        from .conversation_mode import MODE_HUMAN, set_mode

        try:
            await set_mode(
                db,
                tenant_id=tenant_id_of(user),
                channel_id=channel_id,
                contact_phone=contact_phone,
                mode=MODE_HUMAN,
                by=user.id or "human_reply",
                reason="human_reply",
            )
        except Exception as exc:  # noqa: BLE001 - the message already landed
            logger.warning(
                "conversation mode switch failed after human reply "
                "channel=%s: %s", channel_id, exc,
            )
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
    from .meta.providers.base import MetaAPIError
    from .meta.providers.whatsapp import WhatsAppAdapter

    phone_number_id, token, error = await _whatsapp_credentials(db, user, channel)
    if error:
        return "", error

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


async def _whatsapp_credentials(
    db: AsyncSession, user: User, channel: Channel
) -> tuple[str, str, str]:
    """(phone_number_id, token, error) for a channel's WhatsApp number."""
    from .meta.credentials import decrypt_connection_token
    from .meta.models import MetaAsset

    phone_number_id = channel.platform_user_id
    if not phone_number_id:
        return "", "", "This channel has no WhatsApp number attached."

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
        return "", "", "No WhatsApp account is connected for this number."
    if not asset.active:
        return "", "", "This WhatsApp number is not active."

    token = decrypt_connection_token(asset.connection) if asset.connection else None
    if not token:
        return "", "", "WhatsApp credentials are missing. Reconnect the account."
    return phone_number_id, token, ""


async def _dispatch_whatsapp_interactive(
    db: AsyncSession,
    user: User,
    channel: Channel,
    to: str,
    kind: str,
    payload: dict,
) -> tuple[str, str]:
    """(provider_message_id, error) for buttons / list / CTA messages."""
    from .meta.providers.base import MetaAPIError
    from .meta.providers.whatsapp import WhatsAppAdapter

    phone_number_id, token, error = await _whatsapp_credentials(db, user, channel)
    if error:
        return "", error

    adapter = WhatsAppAdapter()
    try:
        if kind == "buttons":
            provider_msg_id = await adapter.send_interactive_buttons(
                phone_number_id, token, to,
                payload["body"], payload["buttons"],
                header=payload.get("header"), footer=payload.get("footer"),
            )
        elif kind == "list":
            provider_msg_id = await adapter.send_interactive_list(
                phone_number_id, token, to,
                payload["body"], payload["button_text"], payload["sections"],
                header=payload.get("header"), footer=payload.get("footer"),
            )
        elif kind == "cta":
            provider_msg_id = await adapter.send_cta_url_message(
                phone_number_id, token, to,
                payload["body"], payload["display_text"], payload["url"],
                header=payload.get("header"), footer=payload.get("footer"),
            )
        else:
            return "", f"Unknown interactive kind {kind!r}"
    except MetaAPIError as exc:
        detail = f"{exc.status_code}: {exc}" if exc.status_code else str(exc)
        return "", detail[:500]
    except ValueError as exc:
        return "", str(exc)[:500]
    if not provider_msg_id:
        return "", "WhatsApp accepted the request but returned no message id."
    return provider_msg_id, ""


async def send_interactive_message(
    channel_id: str,
    *,
    contact_phone: str,
    kind: str,
    payload: dict,
    user: User,
    db: AsyncSession,
    contact_name: str | None = None,
) -> ChannelMessage:
    """Send buttons / a list / a CTA link and record the outcome.

    Same persistence and ownership rules as ``send_message``: the row carries
    the provider's verdict (never optimistic), and a *successful* send means a
    human now owns the thread, so the AI steps back.
    """
    channel = await get_channel(channel_id, user, db)
    if not channel:
        raise ValueError("Channel not found")
    recipient = (contact_phone or "").strip()
    if not recipient:
        raise ValueError("A recipient phone number is required to send")
    if channel.platform != "whatsapp":
        raise ValueError("Interactive messages are only available on WhatsApp")

    from .meta.interactive import readable_content

    if kind == "buttons":
        shown = list(payload.get("buttons") or [])
    elif kind == "list":
        shown = [str(payload.get("button_text") or "")]
        for section in payload.get("sections") or []:
            shown += [str(r.get("title") or "") for r in section.get("rows") or []]
    elif kind == "cta":
        shown = [str(payload.get("display_text") or "")]
    else:
        raise ValueError(f"Unknown interactive kind {kind!r}")

    outbound = ChannelMessage(
        id=str(uuid.uuid4()),
        channel_id=channel_id,
        direction="outbound",
        content=encrypt_message_content(
            readable_content(str(payload.get("body") or ""), shown)
        ),
        content_type="interactive",
        status="sent",
        contact_phone=encrypt_contact_phone(recipient),
        contact_phone_hash=hash_contact_phone(recipient),
        contact_name=contact_name or None,
        handled_by="human",
    )

    try:
        provider_msg_id, error = await _dispatch_whatsapp_interactive(
            db, user, channel, recipient, kind, payload
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

    if not error:
        from .conversation_mode import MODE_HUMAN, set_mode

        try:
            await set_mode(
                db,
                tenant_id=tenant_id_of(user),
                channel_id=channel_id,
                contact_phone=recipient,
                mode=MODE_HUMAN,
                by=user.id or "human_reply",
                reason="human_reply",
            )
        except Exception as exc:  # noqa: BLE001 - the message already landed
            logger.warning(
                "conversation mode switch failed after interactive send "
                "channel=%s: %s", channel_id, exc,
            )
    return outbound


async def whatsapp_number_health(
    channel_id: str, user: User, db: AsyncSession
) -> dict:
    """Meta's quality rating + messaging limit for this channel's number."""
    channel = await get_channel(channel_id, user, db)
    if not channel:
        raise ValueError("Channel not found")
    if channel.platform != "whatsapp":
        raise ValueError("Number health is only available on WhatsApp")
    phone_number_id, token, error = await _whatsapp_credentials(db, user, channel)
    if error:
        raise ValueError(error)
    from .meta.providers.whatsapp import WhatsAppAdapter

    return await WhatsAppAdapter().get_number_health(phone_number_id, token)


async def list_whatsapp_qr_codes(
    channel_id: str, user: User, db: AsyncSession
) -> list[dict]:
    channel = await get_channel(channel_id, user, db)
    if not channel:
        raise ValueError("Channel not found")
    if channel.platform != "whatsapp":
        raise ValueError("QR codes are only available on WhatsApp")
    phone_number_id, token, error = await _whatsapp_credentials(db, user, channel)
    if error:
        raise ValueError(error)
    from .meta.providers.whatsapp import WhatsAppAdapter

    return await WhatsAppAdapter().list_qr_codes(phone_number_id, token)


async def create_whatsapp_qr_code(
    channel_id: str,
    prefilled_message: str,
    user: User,
    db: AsyncSession,
    *,
    image_format: str = "PNG",
) -> dict:
    channel = await get_channel(channel_id, user, db)
    if not channel:
        raise ValueError("Channel not found")
    if channel.platform != "whatsapp":
        raise ValueError("QR codes are only available on WhatsApp")
    phone_number_id, token, error = await _whatsapp_credentials(db, user, channel)
    if error:
        raise ValueError(error)
    from .meta.providers.whatsapp import WhatsAppAdapter

    return await WhatsAppAdapter().create_qr_code(
        phone_number_id, token, prefilled_message, image_format=image_format
    )


async def delete_whatsapp_qr_code(
    channel_id: str, code: str, user: User, db: AsyncSession
) -> bool:
    channel = await get_channel(channel_id, user, db)
    if not channel:
        raise ValueError("Channel not found")
    if channel.platform != "whatsapp":
        raise ValueError("QR codes are only available on WhatsApp")
    phone_number_id, token, error = await _whatsapp_credentials(db, user, channel)
    if error:
        raise ValueError(error)
    from .meta.providers.whatsapp import WhatsAppAdapter

    return await WhatsAppAdapter().delete_qr_code(phone_number_id, token, code)


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

# Message content is encrypted at rest (SEC-M2), so Postgres cannot index it
# or answer a LIKE against it. Search therefore decrypts a bounded window of
# the newest messages instead of the tenant's whole history: one keystroke
# must never become a full-table scan of a multi-year archive. 5,000 rows is
# a few MB of ciphertext and tens of milliseconds of AES per request.
INBOX_SEARCH_MESSAGE_LIMIT = 5000
# Per-channel slice of that budget. One channel gets the whole window; many
# channels each get a fair share so one busy number cannot starve the rest.
# The slice is derived from the total (never a fixed floor) so a tenant with
# thousands of channels still fetches at most INBOX_SEARCH_MESSAGE_LIMIT rows.
# The page size is at most 100; a search for a common word can match
# thousands of threads. Cap the keys we ask Postgres to resolve.
INBOX_SEARCH_MAX_THREADS = 500
# One-character queries match nearly everything. Treat them as "no filter"
# rather than letting them drive the bounded scan.
INBOX_SEARCH_MIN_QUERY_CHARS = 2
# Pre-backfill fallback only (no channel_threads rows exist yet). Bounded so
# a tenant whose summary rows are missing cannot make one inbox load read
# the entire message table.
INBOX_FALLBACK_MESSAGE_LIMIT = 5000


def thread_key(contact_phone: str | None) -> str:
    return contact_phone or UNKNOWN_THREAD_KEY


def _as_utc(value: datetime | None) -> datetime:
    """Normalise SQLite's naive datetimes so Python-side sorts never mix
    aware and naive values."""
    if value is None:
        return datetime.min.replace(tzinfo=timezone.utc)
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


async def _thread_profiles(
    db: AsyncSession,
    tenant_id: str,
    threads: list[ChannelThread],
    by_id: dict[str, Channel],
) -> dict:
    """Load cached contact profiles for a page of threads in one query."""
    profile_keys = {
        (by_id[t.channel_id].platform, decrypt_contact_phone(t.contact_phone))
        for t in threads
        if t.contact_phone is not None and t.channel_id in by_id
    }
    if not profile_keys:
        return {}
    rows = (
        await db.execute(
            select(ContactProfile).where(
                ContactProfile.tenant_id == tenant_id,
                # Match the exact (platform, contact) pairs. Two separate IN
                # clauses would also fetch the cross-product pairs.
                tuple_(
                    ContactProfile.platform, ContactProfile.contact_id
                ).in_(profile_keys),
            )
        )
    ).scalars().all()
    return {(r.platform, r.contact_id): r for r in rows}


async def _thread_lead_categories(
    db: AsyncSession,
    tenant_id: str,
    pairs: set[tuple[str, str]],
) -> dict[tuple[str, str], str]:
    """Canonical lead label for a page of threads, in one indexed query.

    The inbox row stores the per-message conversation category (complaint,
    question); the lead's own category lives on `leads`. Loading it here
    keeps the inbox labels identical to the lead card, digest and escalation
    email instead of re-deriving a label in the browser.
    """
    if not pairs:
        return {}
    rows = (
        await db.execute(
            select(Lead.channel_id, Lead.contact_id, Lead.category).where(
                Lead.tenant_id == tenant_id,
                Lead.merged_into_id.is_(None),
                tuple_(Lead.channel_id, Lead.contact_id).in_(pairs),
            )
        )
    ).all()
    return {
        (channel_id, contact_id): category
        for channel_id, contact_id, category in rows
        if category
    }


def _thread_lead_pairs(threads: list[ChannelThread]) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for t in threads:
        if t.contact_phone is None:
            continue
        phone = decrypt_contact_phone(t.contact_phone)
        if phone:
            pairs.add((t.channel_id, phone))
    return pairs


def _thread_payloads(
    threads: list[ChannelThread],
    by_id: dict[str, Channel],
    profiles: dict,
    lead_categories: dict[tuple[str, str], str] | None = None,
) -> list[dict]:
    """Serialise thread rows for the inbox response."""
    lead_categories = lead_categories or {}
    out: list[dict] = []
    for t in threads:
        ch = by_id.get(t.channel_id)
        if ch is None:
            continue
        phone = t.contact_phone
        decrypted_phone = decrypt_contact_phone(phone) if phone is not None else None
        profile = (
            profiles.get((ch.platform, decrypted_phone))
            if decrypted_phone is not None
            else None
        )
        name = t.contact_name
        if profile is not None and profile.name:
            name = profile.name
        decrypted_last = (
            decrypt_message_content(t.last_message_preview)
            if t.last_message_preview
            else ""
        )
        category = t.category or "normal"
        priority = t.priority or "normal"
        out.append(
            {
                "key": thread_key(decrypted_phone),
                "contact_phone": decrypted_phone,
                "display_name": name or decrypted_phone,
                "username": profile.username if profile else None,
                "avatar_url": profile.avatar_url if profile else None,
                "channel_id": t.channel_id,
                "channel_name": ch.display_name,
                "platform": ch.platform,
                "last_message": (decrypted_last or "")[:280],
                "last_message_at": t.last_message_at.isoformat() if t.last_message_at else None,
                "last_direction": t.last_direction,
                "message_count": int(t.total_count or 0),
                "unread": 0 if phone is None else int(t.unread_count or 0),
                "is_unknown": phone is None,
                "category": category,
                "priority": priority,
                "lead_category": (
                    lead_categories.get((t.channel_id, decrypted_phone))
                    if decrypted_phone is not None
                    else None
                ),
                "important": is_important(priority, category),
                "can_reply": ch.platform != "google_reviews" and phone is not None,
                "archived": t.archived_at is not None,
                "pinned": t.pinned_at is not None,
                "mode": t.conversation_mode or "ai",
                "mode_changed_at": (
                    t.mode_changed_at.isoformat() if t.mode_changed_at else None
                ),
                "mode_changed_by": t.mode_changed_by,
            }
        )
    return out


async def _search_threads(
    db: AsyncSession,
    channel_ids: list[str],
    needle: str,
    limit: int,
    cursor: str | None,
) -> list[ChannelThread]:
    """Find threads whose *recent* messages contain ``needle``.

    The scan is deliberately bounded (see the constants above). It reads the
    newest slice of each channel, decrypts it, keeps the first
    ``INBOX_SEARCH_MAX_THREADS`` matches, then resolves those keys against
    the denormalized thread table so counts and ordering stay authoritative.
    """
    total_budget = INBOX_SEARCH_MESSAGE_LIMIT
    # At least one row per channel so every channel is represented, but the
    # sum across channels never exceeds the total budget.
    per_channel = max(1, total_budget // len(channel_ids))

    scanned: list = []
    for channel_id in channel_ids:
        rows = (
            await db.execute(
                select(
                    ChannelMessage.channel_id,
                    ChannelMessage.contact_phone_hash,
                    ChannelMessage.content,
                    ChannelMessage.created_at,
                )
                .where(ChannelMessage.channel_id == channel_id)
                .order_by(ChannelMessage.created_at.desc())
                .limit(per_channel)
            )
        ).all()
        scanned.extend(rows)

    scanned.sort(key=lambda r: _as_utc(r.created_at), reverse=True)
    del scanned[total_budget:]

    matched: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for row in scanned:
        text = decrypt_message_content(row.content) or ""
        if needle not in text.lower():
            continue
        key = (row.channel_id, row.contact_phone_hash or "__unknown__")
        if key in seen:
            continue
        seen.add(key)
        matched.append(key)
        if len(matched) >= INBOX_SEARCH_MAX_THREADS:
            break
    if not matched:
        return []

    stmt = (
        select(ChannelThread)
        .where(
            tuple_(
                ChannelThread.channel_id, ChannelThread.contact_phone_hash
            ).in_(matched)
        )
        .order_by(ChannelThread.last_message_at.desc())
        .limit(limit)
    )
    if cursor:
        try:
            cursor_dt = datetime.fromisoformat(cursor)
            if cursor_dt.tzinfo is None:
                cursor_dt = cursor_dt.replace(tzinfo=timezone.utc)
            stmt = stmt.where(ChannelThread.last_message_at < cursor_dt)
        except (ValueError, TypeError):
            pass
    return list((await db.execute(stmt)).scalars().all())


async def list_inbox_threads(
    user: User,
    db: AsyncSession,
    search: str | None = None,
    limit: int = 100,
    cursor: str | None = None,
    include_archived: bool = False,
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
    if needle and len(needle) < INBOX_SEARCH_MIN_QUERY_CHARS:
        # A one-character query matches almost everything; show the normal
        # inbox instead of spending the bounded scan on it.
        needle = None

    # Fallback: if no thread rows exist yet (pre-backfill), use the old
    # GROUP BY approach so the inbox is never empty. EXISTS stops at the
    # first row; COUNT(*) would scan every thread a large tenant has on
    # every inbox load just to answer a yes/no question.
    has_threads = (await db.execute(
        select(ChannelThread.id)
        .where(ChannelThread.channel_id.in_(channel_ids))
        .limit(1)
    )).scalar_one_or_none() is not None

    if not has_threads:
        # --- Legacy fallback: GROUP BY (pre-backfill only) ---
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

        # Bounded on purpose: this path only runs before the channel_threads
        # backfill, but a missing backfill must not turn one dashboard load
        # into a full-history read. Newest messages win; older threads are
        # still reachable once the backfill runs.
        all_msgs = (
            await db.execute(
                select(ChannelMessage)
                .where(ChannelMessage.channel_id.in_(channel_ids))
                .order_by(ChannelMessage.created_at.desc())
                .limit(INBOX_FALLBACK_MESSAGE_LIMIT)
            )
        ).scalars().all()

        msgs_by_thread: dict[tuple, list] = {}
        for m in all_msgs:
            key = (m.channel_id, m.contact_phone_hash)
            msgs_by_thread.setdefault(key, []).append(m)

        if needle:
            filtered_summaries = []
            for phone_hash, phone, channel_id, last_at, total in summaries:
                msgs = msgs_by_thread.get((channel_id, phone_hash), [])
                if any(needle in (decrypt_message_content(m.content) or "").lower() for m in msgs):
                    filtered_summaries.append((phone_hash, phone, channel_id, last_at, total))
            summaries = filtered_summaries
            if not summaries:
                return []

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

        lead_pairs: set[tuple[str, str]] = set()
        for _phone_hash, phone, cid, _la, _t in summaries:
            if phone is None:
                continue
            decrypted = decrypt_contact_phone(phone)
            if decrypted:
                lead_pairs.add((cid, decrypted))
        lead_categories = await _thread_lead_categories(
            db, tenant_id_of(user), lead_pairs
        )

        out: list[dict] = []
        for phone_hash, phone, channel_id, last_at, total in summaries:
            msgs = msgs_by_thread.get((channel_id, phone_hash), [])
            if not msgs:
                continue

            last_row = msgs[0]

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
                    "lead_category": (
                        lead_categories.get((channel_id, decrypted_phone))
                        if decrypted_phone is not None
                        else None
                    ),
                    "important": is_important(priority, category),
                    "can_reply": platform != "google_reviews" and phone is not None,
                    # No thread row exists on this path, so nothing has ever
                    # switched the conversation: the AI owns it.
                    "mode": "ai",
                    "mode_changed_at": None,
                    "mode_changed_by": None,
                }
            )
        return out

    # --- Search path: bounded recent-message scan + thread table lookup ---
    if needle:
        threads = await _search_threads(db, channel_ids, needle, limit, cursor)
        if not threads:
            return []
        profiles = await _thread_profiles(db, tenant_id_of(user), threads, by_id)
        lead_categories = await _thread_lead_categories(
            db, tenant_id_of(user), _thread_lead_pairs(threads)
        )
        return _thread_payloads(threads, by_id, profiles, lead_categories)

    # --- Fast path: read from denormalized thread table (1 query) ---
    t_stmt = (
        select(ChannelThread)
        .where(ChannelThread.channel_id.in_(channel_ids))
        .order_by(ChannelThread.pinned_at.desc().nullslast(), ChannelThread.last_message_at.desc())
    )
    if not include_archived:
        t_stmt = t_stmt.where(ChannelThread.archived_at.is_(None))
    if cursor:
        try:
            cursor_dt = datetime.fromisoformat(cursor)
            if cursor_dt.tzinfo is None:
                cursor_dt = cursor_dt.replace(tzinfo=timezone.utc)
            t_stmt = t_stmt.where(ChannelThread.last_message_at < cursor_dt)
        except (ValueError, TypeError):
            pass
    t_stmt = t_stmt.limit(limit)

    threads = (await db.execute(t_stmt)).scalars().all()
    if not threads:
        return []

    profiles = await _thread_profiles(db, tenant_id_of(user), threads, by_id)
    lead_categories = await _thread_lead_categories(
        db, tenant_id_of(user), _thread_lead_pairs(threads)
    )
    return _thread_payloads(threads, by_id, profiles, lead_categories)


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

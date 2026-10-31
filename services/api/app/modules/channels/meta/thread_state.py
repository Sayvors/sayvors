"""Persistence for per-conversation WhatsApp stats (whatsapp_thread_states).

All helpers are best-effort and never raise: stats are an enhancement — a
failure here must never cost the customer their reply.
"""
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from ...channels.service import decrypt_contact_phone, encrypt_contact_phone, hash_contact_phone
from ..models import ChannelMessage, WhatsAppThreadState

logger = logging.getLogger(__name__)


def _as_aware(value: datetime | None) -> datetime | None:
    """SQLite (tests) returns naive datetimes; normalize for comparisons."""
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


async def get_thread_state(db, channel_id: str, contact_phone: str | None) -> WhatsAppThreadState | None:
    if not contact_phone:
        return None
    return (
        await db.execute(
            select(WhatsAppThreadState).where(
                WhatsAppThreadState.channel_id == channel_id,
                WhatsAppThreadState.contact_phone_hash
                == hash_contact_phone(contact_phone),
            )
        )
    ).scalar_one_or_none()


async def set_preferred_language(
    db, channel_id: str, contact_phone: str | None, language: str
) -> None:
    """Pin the language the customer chose. Best-effort, never raises."""
    try:
        state = await get_or_create_thread_state(db, channel_id, contact_phone)
        if state is None:
            return
        state.preferred_language = language
        await db.flush()
    except Exception as e:  # noqa: BLE001 - a stats write must not cost a reply
        logger.warning(
            "preferred language write failed channel=%s: %s", channel_id[:8], e
        )


async def get_or_create_thread_state(
    db, channel_id: str, contact_phone: str | None
) -> WhatsAppThreadState | None:
    if not contact_phone:
        return None
    state = await get_thread_state(db, channel_id, contact_phone)
    if state is None:
        state = WhatsAppThreadState(
            id=str(uuid.uuid4()),
            channel_id=channel_id,
            contact_phone=encrypt_contact_phone(contact_phone),
            contact_phone_hash=hash_contact_phone(contact_phone),
        )
        db.add(state)
        try:
            await db.flush()
        except Exception as e:
            # Lost a race with a concurrent event for the same thread.
            logger.info("Thread state create raced (%s) — refetching", e)
            await db.rollback()
            state = await get_thread_state(db, channel_id, contact_phone)
            if state is None:
                return None
    return state


async def apply_classification(
    db, channel_id: str, contact_phone: str | None, stats: dict
) -> None:
    """Refresh language/confusion from the latest classifier run."""
    try:
        state = await get_or_create_thread_state(db, channel_id, contact_phone)
        if state is None:
            return
        state.language = stats.get("language") or state.language or "en"
        confused = bool(stats.get("confused"))
        state.confused = confused
        if confused:
            state.confused_at = datetime.now(timezone.utc)
        db.add(state)
    except Exception as e:
        logger.info("apply_classification failed channel=%s: %s", channel_id[:8], e)


async def clear_confusion(db, channel_id: str, contact_phone: str | None) -> None:
    """The voice note is the remedy — once delivered, the confusion counts as
    handled: the AI goes back to text. (classify_thread also ignores history
    older than the voice note, so only genuinely fresh confusion re-triggers
    voice.) Best-effort, never raises."""
    try:
        state = await get_thread_state(db, channel_id, contact_phone)
        if state is not None and state.confused:
            state.confused = False
            db.add(state)
    except Exception as e:
        logger.info("clear_confusion failed channel=%s: %s", channel_id[:8], e)


# The legacy 60s one-shot follow-up (awaiting_since/followup_sent) was
# replaced by the durable lead engine (lead_engine.py + lead_action_worker).
# The columns remain in whatsapp_thread_states; nothing writes them anymore.

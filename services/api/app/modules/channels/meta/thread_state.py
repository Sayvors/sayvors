"""Persistence for per-conversation WhatsApp stats (whatsapp_thread_states).

All helpers are best-effort and never raise: stats are an enhancement — a
failure here must never cost the customer their reply.
"""
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from ..models import WhatsAppThreadState

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
                WhatsAppThreadState.contact_phone == contact_phone,
            )
        )
    ).scalar_one_or_none()


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
            contact_phone=contact_phone,
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


async def clear_awaiting(db, channel_id: str, contact_phone: str | None) -> None:
    """The customer answered (or wrote again) — the one-shot follow-up window
    closes and a future question may arm it afresh."""
    try:
        state = await get_thread_state(db, channel_id, contact_phone)
        if state is not None and (state.awaiting_since is not None or state.followup_sent):
            state.awaiting_since = None
            state.followup_sent = False
            db.add(state)
    except Exception as e:
        logger.info("clear_awaiting failed channel=%s: %s", channel_id[:8], e)


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


async def arm_followup(db, channel_id: str, contact_phone: str | None) -> None:
    """The AI's reply asked the customer something — open the 60s window for
    exactly one follow-up. Clearing happens on the next inbound message."""
    try:
        state = await get_or_create_thread_state(db, channel_id, contact_phone)
        if state is None:
            return
        state.awaiting_since = datetime.now(timezone.utc)
        state.followup_sent = False
        db.add(state)
    except Exception as e:
        logger.info("arm_followup failed channel=%s: %s", channel_id[:8], e)


async def mark_followup_sent(db, state: WhatsAppThreadState) -> None:
    """The one-shot fired — close the window so it can never re-arm itself
    (a new customer question goes through arm_followup afresh)."""
    state.awaiting_since = None
    state.followup_sent = True
    db.add(state)
    await db.commit()

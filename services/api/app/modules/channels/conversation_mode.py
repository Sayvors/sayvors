"""Per-conversation AI/human mode.

One column decides whether the AI may speak: ``ChannelThread.conversation_mode``.
Automatic escalation is no longer a separate mute — it is one writer of this
column. That matters because the old design had two independent mute flags
(``Lead.priority`` and the escalation clock) and every bug in this area came
from them disagreeing: a thread could be "important" with no resume armed, or
resumed while the counter still said escalated.

Invariants this module keeps:

- ``ai`` means the AI may answer (subject to the escalation counter, which is
  the *automatic* path's own guard).
- ``human`` means the AI must not answer, whoever set it.
- A human decision is never auto-reversed. ``mode_changed_by`` records the
  source: ``"system"`` is the automatic escalation, and only that value may be
  resumed by the sweep. A user id, ``"human_reply"`` or ``"resolve"`` is a
  person's choice and is left alone.
- Every explicit transition resets the escalation clock and zeroes
  ``ai_miss_count``, so a thread that comes back to the AI starts a clean miss
  cycle instead of re-escalating on the next message (BUG-1's root cause).

Deliberately free of LLM imports: this runs inside the inbound reply path and
inside ``send_message``. Context summarisation lives in
``conversation_context.py`` and is triggered by the callers that can afford it.
"""
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .models import ChannelThread, Lead

logger = logging.getLogger(__name__)

MODE_AI = "ai"
MODE_HUMAN = "human"
MODES = (MODE_AI, MODE_HUMAN)

# The automatic escalation path. Kept as a constant because the resume sweep
# compares against it: only a thread parked by this source may be resumed.
MODE_SOURCE_SYSTEM = "system"


def normalize_mode(value: str | None) -> str:
    """Only an explicit ``"human"`` mutes the AI.

    Deliberately asymmetric. Muting on an unreadable value is the same
    silent-failure class this module exists to remove: a legacy row or a
    corrupted read would stop every reply with no visible cause. The database
    enum rejects values outside the two, so an unknown value means a bug worth
    logging, not a reason to silence a customer.
    """
    if value == MODE_HUMAN:
        return MODE_HUMAN
    if value not in (MODE_AI, None):
        logger.warning("unknown conversation mode %r — treating as ai", value)
    return MODE_AI


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def get_thread(db, channel_id: str, contact_phone: str) -> ChannelThread | None:
    from .service import hash_contact_phone

    return (
        await db.execute(
            select(ChannelThread).where(
                ChannelThread.channel_id == channel_id,
                ChannelThread.contact_phone_hash == hash_contact_phone(contact_phone),
            )
        )
    ).scalar_one_or_none()


async def get_state(db, channel_id: str, contact_phone: str) -> dict:
    """Mode plus who/when changed it, for the inbox thread view."""
    try:
        thread = await get_thread(db, channel_id, contact_phone)
    except Exception as e:  # noqa: BLE001 - a read failure must not mute
        logger.warning(
            "conversation state read failed channel=%s: %s", channel_id, e
        )
        thread = None
    if thread is None:
        return {"mode": MODE_AI, "mode_changed_at": None, "mode_changed_by": None}
    return {
        "mode": normalize_mode(thread.conversation_mode),
        "mode_changed_at": (
            thread.mode_changed_at.isoformat() if thread.mode_changed_at else None
        ),
        "mode_changed_by": thread.mode_changed_by,
    }


async def get_mode(db, channel_id: str, contact_phone: str) -> str:
    """The thread's mode, defaulting to ``ai`` when no row exists yet.

    A missing row means nothing has ever switched this thread, so the AI is the
    default owner — not a reason to mute.
    """
    state = await get_state(db, channel_id, contact_phone)
    return state["mode"]


async def _ensure_thread(
    db, *, tenant_id: str, channel_id: str, contact_phone: str
) -> ChannelThread | None:
    """Get-or-create the thread row without disturbing the caller's work.

    The insert runs inside a SAVEPOINT: losing the race to a concurrent
    message insert must roll back only this attempt. A bare rollback would
    discard the human's outbound row that ``send_message`` has already staged.
    """
    from .service import encrypt_contact_phone, hash_contact_phone

    thread = await get_thread(db, channel_id, contact_phone)
    if thread is not None:
        return thread

    phone_hash = hash_contact_phone(contact_phone)
    thread = ChannelThread(
        id=str(uuid.uuid4()),
        channel_id=channel_id,
        contact_phone=encrypt_contact_phone(contact_phone),
        contact_phone_hash=phone_hash,
        conversation_mode=MODE_AI,
    )
    try:
        async with db.begin_nested():
            db.add(thread)
            await db.flush()
    except IntegrityError:
        # Another worker created it first; use theirs.
        thread = await get_thread(db, channel_id, contact_phone)
        if thread is None:
            logger.warning(
                "conversation thread create raced and refetch missed "
                "channel=%s", channel_id,
            )
            return None
    return thread


async def _lead_for(db, *, channel_id: str, contact_phone: str) -> Lead | None:
    """The lead for this thread.

    ``first()`` rather than ``scalar_one_or_none()``: the (channel, contact)
    index is not unique, and a legacy duplicate row must not turn a mode
    switch into a 500.
    """
    return (
        await db.execute(
            select(Lead)
            .where(
                Lead.channel_id == channel_id,
                Lead.contact_id == contact_phone,
            )
            .order_by(Lead.created_at.asc())
            .limit(1)
        )
    ).scalars().first()


async def _cancel_pending(db, *, channel_id: str, contact_phone: str) -> None:
    """A human-owned thread must not fire a queued AI follow-up."""
    try:
        from .meta.lead_engine import cancel_pending_actions

        await cancel_pending_actions(
            db, channel_id, contact_phone, reason="human_mode"
        )
    except Exception as e:  # noqa: BLE001 - never block the mode change
        logger.warning(
            "pending-action cancel failed channel=%s: %s", channel_id, e
        )


async def set_mode(
    db,
    *,
    tenant_id: str,
    channel_id: str,
    contact_phone: str,
    mode: str,
    by: str,
    reason: str,
    commit: bool = True,
) -> ChannelThread | None:
    """Switch a conversation between AI and human ownership.

    ``by`` is ``"system"`` for the automatic escalation or the acting user's
    id. ``reason`` is stored on the generated context, not on the thread — the
    thread keeps who/when, the context explains why.

    Returns the thread row, or None when it could not be created (the caller
    still proceeds; a mode write failure must not cost the customer a reply).
    """
    if mode not in MODES:
        raise ValueError(f"Unknown conversation mode: {mode}")

    thread = await _ensure_thread(
        db, tenant_id=tenant_id, channel_id=channel_id,
        contact_phone=contact_phone,
    )
    if thread is None:
        return None

    current = normalize_mode(thread.conversation_mode)
    claiming = by != MODE_SOURCE_SYSTEM
    if current == mode:
        # Idempotent, with one exception: a person replying inside an
        # auto-escalated thread is taking ownership. Without this promotion
        # mode_changed_by would stay "system" and the resume sweep would hand
        # the thread back to the AI under the human's feet.
        if not (
            mode == MODE_HUMAN
            and claiming
            and thread.mode_changed_by == MODE_SOURCE_SYSTEM
        ):
            return thread

    thread.conversation_mode = mode
    thread.mode_changed_at = _now()
    thread.mode_changed_by = by

    lead = await _lead_for(
        db, channel_id=channel_id, contact_phone=contact_phone
    )
    if lead is not None:
        if mode == MODE_AI:
            # The single exit path back to the AI: zeroes the counter and
            # clears the escalation clock (BUG-1).
            from .meta.lead_escalation import resume_lead

            resume_lead(lead, reason=reason)
        elif by != MODE_SOURCE_SYSTEM:
            # A person took over: stop the escalation emails and take the
            # thread out of the resume sweep's reach. The automatic path keeps
            # its priority/priority_since because the reminder and the sweep
            # both key on them — that clock is what rescues a thread no human
            # ever picked up.
            lead.priority = "normal"
            lead.ai_miss_count = 0
            lead.priority_since = None
            lead.escalated_at = None
            lead.escalation_reminder_at = None
            lead.handover_sent_at = None
            await _cancel_pending(
                db, channel_id=channel_id, contact_phone=contact_phone
            )

    if commit:
        await db.commit()
    logger.info(
        "conversation mode %s -> %s channel=%s by=%s (%s)",
        current, mode, channel_id, by, reason,
    )
    return thread


async def resolve(db, *, tenant_id: str, channel_id: str, contact_phone: str,
                  user_id: str, commit: bool = True) -> ChannelThread | None:
    """Close a human session and hand the thread back to the AI.

    Always clears the escalation clock, even when the thread is already in AI
    mode. ``set_mode`` is idempotent and returns early on an unchanged mode —
    which is exactly the state a deploy leaves an escalated thread in when the
    migration backfills ``conversation_mode='ai'``. Resolve used to inherit that
    early return, so priority stayed ``important`` and the customer's next
    message re-escalated immediately.
    """
    thread = await set_mode(
        db,
        tenant_id=tenant_id,
        channel_id=channel_id,
        contact_phone=contact_phone,
        mode=MODE_AI,
        by=user_id,
        reason="resolve",
        commit=False,
    )
    # Unconditional: the mode may already have been "ai" while a stale
    # escalation was still armed.
    lead = await _lead_for(
        db, channel_id=channel_id, contact_phone=contact_phone
    )
    if lead is not None:
        from .meta.lead_escalation import resume_lead

        resume_lead(lead, reason="resolve")
    if commit:
        await db.commit()
    return thread

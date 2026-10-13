"""Lead importance escalation: counter, priority, handover state.

The only place `priority` is ever written. `ai_miss_count` is the sole input
that moves it, so the two cannot drift -- fixing the counter logic corrects
priority automatically, and there is no second writer to disagree with it.

Deliberately free of LLM imports. The counter is history arithmetic: a
scheduling bug must be debuggable in a database row, not in a prompt. That
invariant is enforced by test_lead_engine.py's scan of the lead modules.

See docs/specs/2026-10-13-lead-priority-escalation-design.md.
"""

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from ..models import ChannelMessage, Lead

logger = logging.getLogger(__name__)

#: Consecutive "AI replied, customer wrote again" cycles before a lead is
#: escalated. Fixed, not tenant-configurable (spec, non-goals).
ESCALATION_THRESHOLD = 3

#: A handover silences the AI. If no human picks the lead up within this
#: long, the AI resumes -- otherwise a misrouted escalation silently starves
#: the customer. Safety requirement, not a nicety.
HANDOVER_RESUME_HOURS = 24

#: Reminder window after the escalation email. NULL is terminal -- "already
#: reminded, or never armed" -- never "not yet".
REMINDER_DELAY = timedelta(hours=4)

# Cleared whenever a lead leaves 'important'. Without this a re-escalation
# would read the stale NULL reminder as already-handled and send nothing.
_ESCALATION_FIELDS = (
    "priority_since",
    "escalated_at",
    "escalation_reminder_at",
    "handover_sent_at",
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _clear_escalation_state(lead) -> None:
    for field in _ESCALATION_FIELDS:
        setattr(lead, field, None)


async def _latest_outbound(db, lead):
    """The most recent outbound row in the thread, or None."""
    return (
        await db.execute(
            select(ChannelMessage)
            .where(
                ChannelMessage.channel_id == lead.channel_id,
                ChannelMessage.contact_phone == lead.contact_id,
                ChannelMessage.direction == "outbound",
            )
            .order_by(ChannelMessage.created_at.desc())
            .limit(1)
        )
    ).scalars().first()


async def update_escalation_state(db, lead) -> None:
    """Update the counter, then recompute priority. The only writer of both.

    Call immediately after persisting an inbound ChannelMessage. Increments
    when the previous outbound was AI-authored, resets to 0 otherwise -- a
    human reply clears the thread because the AI is no longer the last voice.
    """
    previous = await _latest_outbound(db, lead)
    previous_is_ai = None if previous is None else bool(previous.is_ai)
    lead.ai_miss_count = (lead.ai_miss_count or 0) + 1 if previous_is_ai else 0

    was_important = lead.priority == "important"
    if (lead.ai_miss_count or 0) >= ESCALATION_THRESHOLD:
        if was_important:
            return
        # Entering: a fresh escalation. Clearing here is what makes a
        # re-escalation send a second email rather than reading the previous
        # cycle's NULL reminder as already handled.
        _clear_escalation_state(lead)
        lead.priority = "important"
        lead.priority_since = _now()
        await on_escalate(db, lead)
        return

    if was_important:
        lead.priority = "normal"
        _clear_escalation_state(lead)


def should_ai_reply(lead) -> bool:
    """False while the thread is handed to a human."""
    return (lead.priority or "normal") != "important"


def _lead_label(lead) -> str:
    return lead.contact_name or lead.contact_id or "A customer"


HANDOVER_TEXT = "Let me get my colleague to help you with this."
ESCALATION_SUBJECT = "A lead needs you: {name}"


async def _send_email(to, subject, message, cta_url: str | None = None) -> str:
    """Indirection so tests can intercept without patching Resend internals."""
    from ...email.service import send_notification_email

    return await send_notification_email(to, subject, message, cta_url)


async def resolve_recipients(db, lead) -> list[str]:
    """Where the escalation goes.

    lead_settings.escalation_emails when set, otherwise the tenant owner's
    signup email. The fallback is a guaranteed-existing row -- Lead.tenant_id
    IS User.id, which the consumer already relies on for response_style -- so
    escalation works with zero configuration and a tenant that adds recipients
    keeps the owner only if they leave the list empty.
    """
    from ...users.models import User

    row = (
        await db.execute(
            select(User.lead_settings).where(User.id == lead.tenant_id)
        )
    ).scalar_one_or_none()
    configured = (row or {}).get("escalation_emails")
    cleaned = (
        [e.strip().lower() for e in configured if isinstance(e, str) and e.strip()]
        if isinstance(configured, list) else []
    )
    if cleaned:
        return sorted(set(cleaned))

    owner_email = (
        await db.execute(select(User.email).where(User.id == lead.tenant_id))
    ).scalar_one_or_none()
    return [owner_email] if owner_email else []


async def on_escalate(db, lead) -> None:
    """Side effects on entering 'important'. Never raises.

    One in-app notification plus one escalation email. Neither may be able to
    break message handling, so every call is guarded.
    """
    try:
        from ...channels.realtime import publish_inbox_event

        await publish_inbox_event(lead.tenant_id, {
            "type": "notification",
            "notification": {
                "kind": "lead_escalated",
                "channel_id": lead.channel_id,
                "contact_id": lead.contact_id,
                "contact_name": lead.contact_name,
                "preview": "The AI could not resolve this conversation.",
            },
        })
    except Exception as e:
        logger.warning("escalation inbox event failed for lead %s: %s", lead.id, e)

    try:
        recipients = await resolve_recipients(db, lead)
    except Exception as e:
        logger.warning("escalation recipient lookup failed for lead %s: %s", lead.id, e)
        return

    if not recipients:
        logger.warning("lead %s escalated with no recipient", lead.id)
        return

    try:
        await _send_email(
            recipients,
            ESCALATION_SUBJECT.format(name=_lead_label(lead)),
            (
                f"{_lead_label(lead)} kept writing after the AI replied "
                f"{lead.ai_miss_count} times. The AI has stopped replying so "
                f"someone can take over."
            ),
            cta_url=f"/dashboard/inbox?channel={lead.channel_id}&key={lead.contact_id}",
        )
    except Exception as e:
        # escalated_at stays NULL and no reminder is armed: we cannot claim a
        # human was told. Re-entering 'important' retries from scratch.
        logger.warning("escalation email failed for lead %s: %s", lead.id, e)
        return

    lead.escalated_at = _now()
    lead.escalation_reminder_at = _now() + REMINDER_DELAY
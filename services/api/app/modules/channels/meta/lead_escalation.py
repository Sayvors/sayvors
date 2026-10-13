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

# Fallbacks used only when a tenant row cannot be read. The real defaults
# live in lead_engine.SETTINGS_DEFAULTS so they are configurable per tenant
# through lead_settings; these mirror them for the failure path.
_FALLBACK_THRESHOLD = 3
_FALLBACK_RESUME_HOURS = 24
_FALLBACK_REMINDER_HOURS = 4

# Per-tenant escalation settings, cached for the lifetime of one sweep so a
# 50-row batch issues at most one query per distinct tenant rather than one
# per lead.
_settings_cache: dict[str, dict] = {}


def clear_settings_cache() -> None:
    """Drop the per-tenant settings cache. Called at the end of each sweep."""
    _settings_cache.clear()


async def load_settings(db, tenant_id: str) -> dict:
    """Escalation knobs for one tenant, normalised and clamped.

    Never raises: a missing or malformed row falls back to the defaults,
    because failing to read a setting must never stop a customer getting a
    reply.
    """
    from ...users.models import User
    from .lead_engine import normalize_lead_settings

    cached = _settings_cache.get(tenant_id)
    if cached is not None:
        return cached
    try:
        row = (
            await db.execute(
                select(User.lead_settings).where(User.id == tenant_id)
            )
        ).scalar_one_or_none()
        settings = normalize_lead_settings(row)
    except Exception as e:
        logger.warning("escalation settings read failed for %s: %s", tenant_id, e)
        settings = normalize_lead_settings(None)
    _settings_cache[tenant_id] = settings
    return settings


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

    tenant_settings = await load_settings(db, lead.tenant_id)
    threshold = tenant_settings["escalation_threshold"]

    was_important = lead.priority == "important"
    if (lead.ai_miss_count or 0) >= threshold:
        if was_important:
            return
        # Entering: a fresh escalation. Clearing here is what makes a
        # re-escalation send a second email rather than reading the previous
        # cycle's NULL reminder as already handled.
        _clear_escalation_state(lead)
        lead.priority = "important"
        lead.priority_since = _now()
        await on_escalate(db, lead, tenant_settings)
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

    tenant_settings = await load_settings(db, lead.tenant_id)
    configured = tenant_settings.get("escalation_emails") or []
    if configured:
        return list(configured)

    owner_email = (
        await db.execute(select(User.email).where(User.id == lead.tenant_id))
    ).scalar_one_or_none()
    return [owner_email] if owner_email else []


async def on_escalate(db, lead, tenant_settings: dict | None = None) -> None:
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
    reminder_hours = (tenant_settings or {}).get(
        "escalation_reminder_hours", _FALLBACK_REMINDER_HOURS
    )
    lead.escalation_reminder_at = _now() + timedelta(hours=reminder_hours)


async def send_handover(db, lead, adapter, phone_number_id: str, token: str) -> None:
    """Deliver the holding line, once.

    Guarded by handover_sent_at so a re-trigger never repeats it. On failure
    the column stays NULL: the thread still goes silent (the handover is about
    the AI stopping, not the message landing) and a failed cosmetic line must
    not block the escalation itself.
    """
    if lead.handover_sent_at is not None:
        return
    try:
        await adapter.send_text_message(
            phone_number_id, token, lead.contact_id, HANDOVER_TEXT
        )
        lead.handover_sent_at = _now()
    except Exception as e:
        logger.warning("handover line failed for lead %s: %s", lead.id, e)


async def escalate_to_human(db, lead, adapter, phone_number_id: str, token: str) -> None:
    """Hand a thread to a human: cancel queued nudges, say so once, stop.

    Called by the consumer when a thread is 'important' at reply time. After
    this the AI stays silent for the thread until the 24h resume sweep.
    """
    from .lead_engine import cancel_pending_actions

    try:
        await cancel_pending_actions(
            db, lead.channel_id, lead.contact_id, reason="escalated"
        )
    except Exception as e:
        logger.warning("handover cancel failed for lead %s: %s", lead.id, e)
    await send_handover(db, lead, adapter, phone_number_id, token)


async def run_reminder_sweep(db, limit: int = 50) -> int:
    """Send the single 4h reminder for leads still awaiting a human.

    Bounded and index-friendly: the partial index ix_leads_pending_reminder
    means this never walks more than the handful of rows actually due, so it
    is safe to call on every tick even with millions of leads.
    """
    now = _now()
    rows = (
        await db.execute(
            select(Lead)
            .where(
                Lead.priority == "important",
                Lead.escalation_reminder_at.isnot(None),
                Lead.escalation_reminder_at <= now,
            )
            .order_by(Lead.escalation_reminder_at.asc())
            .limit(limit)
        )
    ).scalars().all()

    sent = 0
    for lead in rows:
        if lead.priority != "important":
            # A human reply already reset the counter and dropped priority.
            lead.escalation_reminder_at = None
            continue
        try:
            recipients = await resolve_recipients(db, lead)
            tenant_settings = await load_settings(db, lead.tenant_id)
            resume_hours = tenant_settings["escalation_resume_hours"]
            if not recipients:
                logger.warning("lead %s reminder has no recipient", lead.id)
            else:
                await _send_email(
                    recipients,
                    ESCALATION_SUBJECT.format(name=_lead_label(lead)),
                    (
                        f"Still no reply on {_lead_label(lead)} after the "
                        f"escalation. The AI will resume in {resume_hours}h "
                        f"if nobody picks it up."
                    ),
                    cta_url=(
                        f"/dashboard/inbox?channel={lead.channel_id}"
                        f"&key={lead.contact_id}"
                    ),
                )
                sent += 1
        except Exception as e:
            # Leave the timestamp armed: a failed reminder must retry, or the
            # lead is silently dropped with no second notification.
            logger.warning("escalation reminder failed for lead %s: %s", lead.id, e)
            continue
        lead.escalation_reminder_at = None    # NULL = terminal, never again
    return sent


async def run_resume_sweep(db, limit: int = 50) -> int:
    """Hand threads back to the AI after the tenant's resume window with no
    human acting.

    Without this a misrouted escalation silently starves the customer: the
    thread is muted, the email went nowhere, and nothing ever puts it back.

    Deliberately does NOT require handover_sent_at. If the holding line fails
    to send the thread is still silent, so keying on that column would strand
    exactly the leads most likely to need rescuing.

    The cutoff is per-tenant, so this cannot be a single indexed predicate
    across the whole table -- but each row is filtered in Python after the
    (priority, priority_since) index narrows the candidates, and the batch is
    capped, so the cost stays bounded.
    """
    horizon = _now() - timedelta(hours=_FALLBACK_RESUME_HOURS)
    rows = (
        await db.execute(
            select(Lead)
            .where(
                Lead.priority == "important",
                Lead.priority_since.isnot(None),
                # Pre-filter with the loosest possible window so the index
                # still does the narrowing; the real per-tenant cutoff is
                # applied below.
                Lead.priority_since <= horizon,
            )
            .order_by(Lead.priority_since.asc())
            .limit(limit)
        )
    ).scalars().all()

    resumed = 0
    for lead in rows:
        tenant_settings = await load_settings(db, lead.tenant_id)
        own_cutoff = _now() - timedelta(
            hours=tenant_settings["escalation_resume_hours"]
        )
        if lead.priority_since > own_cutoff:
            continue        # this tenant allows longer
        lead.priority = "normal"
        _clear_escalation_state(lead)
        resumed += 1
        logger.info(
            "lead %s handed back to the AI: no human action within %sh",
            lead.id, tenant_settings["escalation_resume_hours"],
        )
    return resumed
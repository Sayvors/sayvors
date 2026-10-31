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
import re
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from ...channels.service import (
    encrypt_contact_phone,
    encrypt_message_content,
    hash_contact_phone,
)
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


async def load_settings(db, tenant_id: str, *, use_cache: bool = True) -> dict:
    """Escalation knobs for one tenant, normalised and clamped.

    Never raises: a missing or malformed row falls back to the defaults,
    because failing to read a setting must never stop a customer getting a
    reply.

    ``use_cache=False`` is for UI reads. The cache lives for a sweep batch and
    is only cleared when one finishes, so showing a thread the cached value
    would keep promising an old resume window after the owner changed it.
    """
    from ...users.models import User
    from .lead_engine import normalize_lead_settings

    if use_cache:
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
    if use_cache:
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
    h = hash_contact_phone(lead.contact_id)
    return (
        await db.execute(
            select(ChannelMessage)
            .where(
                ChannelMessage.channel_id == lead.channel_id,
                ChannelMessage.direction == "outbound",
                (ChannelMessage.contact_phone_hash == h)
                | (ChannelMessage.contact_phone_hash.is_(None)
                   & (ChannelMessage.contact_phone == lead.contact_id)),
            )
            .order_by(ChannelMessage.created_at.desc())
            .limit(1)
        )
    ).scalars().first()


async def update_escalation_state(db, lead, *, confused: bool = False, urgent: bool = False) -> None:
    """Update the counter, then recompute priority. The only writer of both.

    Call immediately after persisting an inbound ChannelMessage.

    ``confused`` is the thread classifier's signal that the customer came back
    lost ("what?", the same question again after an answer). That -- not "the
    customer wrote again" -- is what an AI miss is: counting every follow-up
    muted healthy question-and-answer threads after three turns, which is the
    bug this fixes.

    ``urgent`` comes from ``detect_urgency`` and escalates immediately: a
    customer who says "urgent" or "right now" should not wait for a counter.
    """
    previous = await _latest_outbound(db, lead)
    previous_is_ai = None if previous is None else bool(previous.is_ai)
    if previous_is_ai and confused:
        lead.ai_miss_count = (lead.ai_miss_count or 0) + 1
    else:
        lead.ai_miss_count = 0

    tenant_settings = await load_settings(db, lead.tenant_id)
    threshold = tenant_settings["escalation_threshold"]

    was_important = lead.priority == "important"
    # threshold 0 = counter disabled. Urgency is evaluated on its own line
    # below so "0" never means "never escalate at all".
    count_triggered = threshold > 0 and (lead.ai_miss_count or 0) >= threshold
    if urgent or count_triggered:
        if was_important:
            return
        # Entering: a fresh escalation. Clearing here is what makes a
        # re-escalation send a second email rather than reading the previous
        # cycle's NULL reminder as already handled.
        _clear_escalation_state(lead)
        lead.priority = "important"
        lead.priority_since = _now()
        await on_escalate(db, lead, tenant_settings, reason="urgent" if urgent else "confused")
        return

    if was_important:
        # A human reply already reset the counter above; set it explicitly so
        # no future branch can leave a stale escalated value behind.
        lead.priority = "normal"
        lead.ai_miss_count = 0
        _clear_escalation_state(lead)


# Urgency markers: English and the Arabic/Urdu forms customers actually type.
# Word-boundary matched so a substring can never trip it ("nowadays" is not
# "now"). "today" is deliberately absent: "what are your hours today?" is a
# normal question, not an emergency.
_URGENT_PATTERNS = (
    r"\b(urgent|urgently|asap|as\s+soon\s+as\s+possible|immediately|"
    r"right\s+away|right\s+now|emergency|time[- ]sensitive|"
    r"quickly|hurry|rush|promptly|fast\s+as\s+possible|"
    r"quick(?!\s+question))\b",
    r"(عاجل|عاجلا|بسرعة|سريع|بأسرع وقت|بأقرب وقت|حالا|حالاً|فورا|فوراً|"
    r"ضروري|الان|الآن|على وجه السرعة)",
    r"\b(still\s+waiting|no\s+one\s+(?:has\s+)?(?:replied|answered)|"
    r"keeps?\s+ignoring|third\s+time)\b",
)


def detect_urgency(text: str | None) -> bool:
    """True when the customer is saying this cannot wait.

    Deliberately deterministic and free: an LLM round-trip on every inbound to
    decide whether to page a human is slower than the reply it is meant to
    rescue, and a classifier outage must not disable the safety path.
    """
    if not text:
        return False
    lowered = text.lower()
    return any(re.search(pattern, lowered) for pattern in _URGENT_PATTERNS)


def should_ai_reply(lead, mode: str = "ai") -> bool:
    """False while a human owns the thread or an escalation is unresolved.

    ``mode`` comes from ``ChannelThread.conversation_mode``. The priority check
    stays as well: automatic escalation sets both, and if the thread-row write
    ever fails the mute must still hold rather than let the AI talk over a
    person.
    """
    from ...channels.conversation_mode import MODE_HUMAN

    if mode == MODE_HUMAN:
        return False
    return (lead.priority or "normal") != "important"


def resume_lead(lead, reason: str) -> None:
    """Hand a thread back to the AI.

    Zeroing ``ai_miss_count`` is the invariant that makes this stick. The
    counter is the only input to ``priority``, so leaving it at the escalated
    value meant the very next inbound incremented past the threshold and
    muted the customer again — the 24h resume sweep appeared to work while
    every following message re-escalated instantly (BUG-1). Every path that
    returns a thread to the AI goes through here.
    """
    lead.priority = "normal"
    lead.ai_miss_count = 0
    _clear_escalation_state(lead)
    logger.info("lead %s handed back to the AI (%s)", lead.id, reason)


def _lead_label(lead) -> str:
    return lead.contact_name or lead.contact_id or "A customer"


HANDOVER_TEXT = "Let me get my colleague to help you with this."
# Urgent handovers need their own line: "let me get a colleague" reads as a
# deflection to someone who just said it cannot wait.
URGENT_HANDOVER_TEXT = (
    "Understood — I've flagged this as urgent. A team member will pick it up "
    "here shortly."
)
ESCALATION_SUBJECT = "A lead needs you: {name}"


def _absolute(path: str | None) -> str | None:
    """Turn an in-app path into the absolute URL an email CTA has to be.

    send_notification_email rejects anything that is not http(s), and every
    escalation and reminder was passing `/dashboard/inbox?...` straight in.
    That raised ValueError on every send, the caller caught it and logged a
    warning, and the escalation email -- the thing that tells a human the AI
    has stopped replying -- never arrived. Re-entering 'important' retried and
    failed identically, so it was silent and permanent.

    Returns None rather than a broken link when FRONTEND_URL is unset, so a
    misconfigured environment loses the button and not the whole email.
    """
    if not path:
        return None
    if path.startswith(("http://", "https://")):
        return path
    from ....config import settings

    base = (settings.FRONTEND_URL or "").rstrip("/")
    if not base:
        return None
    return f"{base}/{path.lstrip('/')}"


async def _send_email(to, subject, message, cta_url: str | None = None) -> str:
    """Indirection so tests can intercept without patching Resend internals."""
    from ...email.service import send_notification_email

    return await send_notification_email(to, subject, message, _absolute(cta_url))


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


async def on_escalate(db, lead, tenant_settings: dict | None = None,
                      reason: str = "confused") -> None:
    """Side effects on entering 'important'. Never raises.

    One in-app notification plus one escalation email. Neither may be able to
    break message handling, so every call is guarded. ``reason`` lets the page
    say *why* it fired: "urgent" means the customer said so, "confused" means
    the counter tripped.
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
                "preview": (
                    "The customer asked for something urgent."
                    if reason == "urgent"
                    else "The AI could not resolve this conversation."
                ),
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

    body = (
        f"{_lead_label(lead)} said their request is urgent. The AI has stopped "
        f"replying so someone can take over now."
        if reason == "urgent"
        else (
            f"{_lead_label(lead)} came back confused {lead.ai_miss_count} "
            f"times after an AI reply. The AI has stopped replying so someone "
            f"can take over."
        )
    )

    try:
        await _send_email(
            recipients,
            ESCALATION_SUBJECT.format(name=_lead_label(lead)),
            body,
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


async def _persist_handover(db, lead, provider_msg_id: str | None, text: str = HANDOVER_TEXT) -> None:
    """Store the holding line as a normal outbound row.

    Without this the inbox, the lead digest and the escalation counter never
    saw the message the customer actually received: the thread looked
    unanswered in the dashboard while WhatsApp showed a reply (BUG-3).
    ``is_ai`` stays False on purpose — the holding line is the AI stepping
    aside, so a later inbound must reset the miss counter rather than count
    this row as another AI miss.
    """
    platform = lead.platform or "whatsapp"
    # contact_id is NOT NULL on Lead, but an empty value would still crash the
    # phone hash, so the guard is explicit rather than implied.
    contact = lead.contact_id or ""
    row = ChannelMessage(
        id=str(uuid.uuid4()),
        channel_id=lead.channel_id,
        platform_message_id=(provider_msg_id or "")[:200] or None,
        direction="outbound",
        content=encrypt_message_content(text),
        content_type="text",
        status="sent",
        contact_phone=encrypt_contact_phone(contact or None),
        contact_phone_hash=hash_contact_phone(contact) if contact else None,
        is_ai=False,
        handled_by="system",
    )
    db.add(row)
    # Committed here because the message already reached the customer: the
    # row must survive even if the caller's transaction later rolls back.
    await db.commit()

    try:
        from ...channels.realtime import publish_inbox_event

        await publish_inbox_event(lead.tenant_id, {
            "type": "message",
            "id": row.id,
            "channel_id": lead.channel_id,
            "platform": platform,
            "direction": "outbound",
            "content": text,
            "content_type": "text",
            "status": "sent",
            "contact_phone": lead.contact_id,
            "created_at": row.created_at,
        })
    except Exception as e:
        logger.warning(
            "handover realtime publish failed for lead %s: %s", lead.id, e
        )


async def send_handover(db, lead, adapter, phone_number_id: str, token: str,
                        urgent: bool = False) -> None:
    """Deliver the holding line, once, and record it.

    Guarded by handover_sent_at so a re-trigger never repeats it. A send
    failure leaves the column NULL: the thread still goes silent (the
    handover is about the AI stopping, not the message landing) and a failed
    cosmetic line must not block the escalation itself. A persistence failure
    after a successful send is logged but does not reopen the send — the
    customer already has the message.

    ``urgent`` picks the acknowledgement that matches why the page fired.
    """
    if lead.handover_sent_at is not None:
        return
    text = URGENT_HANDOVER_TEXT if urgent else HANDOVER_TEXT
    try:
        provider_msg_id = await adapter.send_text_message(
            phone_number_id, token, lead.contact_id, text
        )
        lead.handover_sent_at = _now()
    except Exception as e:
        logger.warning("handover line failed for lead %s: %s", lead.id, e)
        return
    try:
        await _persist_handover(db, lead, provider_msg_id, text)
    except Exception as e:
        logger.error(
            "handover line sent but not persisted for lead %s: %s", lead.id, e
        )


async def _publish_mode(db, lead, *, mode: str) -> None:
    """Broadcast a system mode change so open inbox tabs update live.

    The router publishes this for human actions. The automatic paths must too,
    or an already-open thread keeps showing the old owner — and, after BUG-4,
    no escalation clock — until someone reopens it. Best-effort: a realtime
    failure must never affect the escalation itself.
    """
    try:
        from ...channels.realtime import publish_inbox_event

        settings = await load_settings(db, lead.tenant_id)
        hours = int(settings["escalation_resume_hours"])
        since = lead.priority_since
        if since is not None and since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
        resume_at = None
        if (lead.priority or "normal") == "important" and since is not None:
            resume_at = (since + timedelta(hours=hours)).isoformat()

        def _iso(value):
            return value.isoformat() if value else None

        await publish_inbox_event(lead.tenant_id, {
            "type": "mode",
            "channel_id": lead.channel_id,
            "contact_phone": lead.contact_id,
            "mode": mode,
            "mode_changed_at": datetime.now(timezone.utc).isoformat(),
            "mode_changed_by": "system",
            "priority": lead.priority or "normal",
            "ai_miss_count": int(lead.ai_miss_count or 0),
            "priority_since": _iso(since),
            "escalated_at": _iso(lead.escalated_at),
            "escalation_reminder_at": _iso(lead.escalation_reminder_at),
            "handover_sent_at": _iso(lead.handover_sent_at),
            "escalation_resume_hours": hours,
            "resume_at": resume_at,
        })
    except Exception as e:  # noqa: BLE001 - never break the escalation
        logger.warning("mode event failed for lead %s: %s", lead.id, e)


async def escalate_to_human(db, lead, adapter, phone_number_id: str, token: str,
                            urgent: bool = False) -> None:
    """Hand a thread to a human: cancel queued nudges, say so once, stop.

    Called by the consumer when a thread is 'important' at reply time. This is
    the automatic writer of ``conversation_mode`` — the thread row records
    ``mode_changed_by="system"`` so the resume sweep knows it may reverse the
    mute, unlike a mode a person set. After this the AI stays silent until the
    resume sweep or a human resolve.
    """
    from ...channels.conversation_mode import MODE_HUMAN, MODE_SOURCE_SYSTEM, set_mode
    from .lead_engine import cancel_pending_actions

    # Mode first: a failed send below must not leave the thread writable by
    # the AI. Resetting the escalation clock is deliberately skipped here —
    # the sweep and the reminder email both key on it, and that clock is what
    # rescues a thread nobody picks up.
    await set_mode(
        db,
        tenant_id=lead.tenant_id,
        channel_id=lead.channel_id,
        contact_phone=lead.contact_id,
        mode=MODE_HUMAN,
        by=MODE_SOURCE_SYSTEM,
        reason="escalation",
        commit=False,
    )
    await _publish_mode(db, lead, mode=MODE_HUMAN)

    try:
        await cancel_pending_actions(
            db, lead.channel_id, lead.contact_id, reason="escalated"
        )
    except Exception as e:
        logger.warning("handover cancel failed for lead %s: %s", lead.id, e)
    await send_handover(db, lead, adapter, phone_number_id, token, urgent=urgent)


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
        # A person took this thread over (or replied in it): the sweep must
        # not hand it back to the AI under them. Only a mute this sweep arm
        # itself — mode_changed_by="system" — is auto-reversible.
        thread = await _thread_for(db, lead)
        if thread is not None and (thread.mode_changed_by or "") not in (
            "", "system",
        ):
            logger.info(
                "lead %s kept in human mode by %s — sweep skipped",
                lead.id, thread.mode_changed_by,
            )
            continue
        resume_lead(
            lead,
            reason=(
                "no human action within "
                f"{tenant_settings['escalation_resume_hours']}h"
            ),
        )
        await _set_mode_from_system(db, lead, reason="auto_resume")
        resumed += 1
    return resumed


async def _thread_for(db, lead):
    """The thread row for this lead, if one exists."""
    from ...channels.conversation_mode import get_thread

    try:
        return await get_thread(db, lead.channel_id, lead.contact_id)
    except Exception as e:  # noqa: BLE001 - never block the sweep
        logger.warning("thread lookup failed for lead %s: %s", lead.id, e)
        return None


async def _set_mode_from_system(db, lead, *, reason: str) -> None:
    """Mirror a resume onto the thread row. Best-effort, never raises."""
    from ...channels.conversation_mode import (
        MODE_AI,
        MODE_SOURCE_SYSTEM,
        set_mode,
    )

    try:
        await set_mode(
            db,
            tenant_id=lead.tenant_id,
            channel_id=lead.channel_id,
            contact_phone=lead.contact_id,
            mode=MODE_AI,
            by=MODE_SOURCE_SYSTEM,
            reason=reason,
            commit=False,
        )
    except Exception as e:  # noqa: BLE001 - the lead is already resumed
        logger.warning("mode mirror failed for lead %s: %s", lead.id, e)
        return
    await _publish_mode(db, lead, mode=MODE_AI)
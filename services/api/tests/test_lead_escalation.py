"""Tests for lead qualification gating and importance escalation.

See docs/specs/2026-10-13-lead-priority-escalation-design.md.
"""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.modules.channels.models import Channel, ChannelMessage, Lead
from app.modules.users.models import User

QUIET_OFF = {"quiet_start_hour": 0, "quiet_end_hour": 0}


async def _seed_lead(db, *, stage: str = "qualified", phone: str = "+15550000001"):
    uid = f"gate-user-{uuid.uuid4().hex[:8]}"
    db.add(User(
        id=uid, first_name="G", last_name="A",
        email=f"{uid}@example.com", password_hash="x",
        lead_settings=dict(QUIET_OFF),
    ))
    channel = Channel(
        id=f"gate-chan-{uuid.uuid4().hex[:8]}", user_id=uid,
        platform="whatsapp", platform_user_id=phone,
        display_name="Gate", status="active",
    )
    db.add(channel)
    await db.flush()
    lead = Lead(
        id=f"gate-lead-{uuid.uuid4().hex[:8]}", tenant_id=uid,
        channel_id=channel.id, platform="whatsapp", contact_id="+966500000001",
        stage=stage, language="en", opt_out=False, thread_key="+966500000001",
    )
    db.add(lead)
    await db.commit()
    return lead, channel


async def _seed_thread(db, *, last_outbound_is_ai: bool | None, count: int, phone: str = "+15550000002"):
    """Seed a qualified lead plus `count` inbound messages, optionally
    preceded by an outbound so the counter increments."""
    lead, channel = await _seed_lead(db, phone=phone)
    base = datetime.now(timezone.utc) - timedelta(hours=5)
    if last_outbound_is_ai is not None:
        db.add(ChannelMessage(
            id=str(uuid.uuid4()), channel_id=channel.id, direction="outbound",
            content="ai reply", content_type="text", status="sent",
            contact_phone=lead.contact_id, is_ai=last_outbound_is_ai,
            created_at=base,
        ))
        await db.flush()
    for i in range(count):
        db.add(ChannelMessage(
            id=str(uuid.uuid4()), channel_id=channel.id, direction="inbound",
            content=f"still waiting {i}", content_type="text", status="delivered",
            contact_phone=lead.contact_id,
            created_at=base + timedelta(minutes=i + 1),
        ))
    await db.commit()
    return lead


@pytest.mark.asyncio
async def test_schedule_followup_refuses_unqualified_lead(db):
    """A lead that never showed buying intent must not get a sales sequence.

    Regression guard for the real defect: capture_lead creates a Lead for every
    inbound DM, and schedule_followup only checked opt_out/stage-closed, so a
    customer who said "hello" received three nudges across 72 hours the moment
    the AI's reply happened to end in a question mark.
    """
    from app.modules.channels.meta.lead_engine import schedule_followup

    lead, channel = await _seed_lead(db, stage="new")

    refused = await schedule_followup(
        db, lead=lead, channel_id=channel.id, contact_id=lead.contact_id,
        platform="whatsapp", guard_message_id="wamid-gate-1",
        question="What do you need?", settings=dict(QUIET_OFF),
    )
    assert refused is None, "unqualified lead must not be armed"

    lead.stage = "qualified"
    await db.commit()

    armed = await schedule_followup(
        db, lead=lead, channel_id=channel.id, contact_id=lead.contact_id,
        platform="whatsapp", guard_message_id="wamid-gate-1",
        question="What do you need?", settings=dict(QUIET_OFF),
    )
    assert armed is not None, "qualified lead must be armed"


@pytest.mark.asyncio
async def test_counter_increments_after_ai_reply(db):
    from app.modules.channels.meta.lead_escalation import update_escalation_state

    lead = await _seed_thread(db, last_outbound_is_ai=True, count=1)
    await update_escalation_state(db, lead)
    await db.commit()
    assert lead.ai_miss_count == 1
    assert lead.priority == "normal"      # below threshold


@pytest.mark.asyncio
async def test_counter_resets_after_human_reply(db):
    """is_ai is a stored flag, not text matching -- a human whose message
    reads like the AI's must still reset the counter."""
    from app.modules.channels.meta.lead_escalation import update_escalation_state

    lead = await _seed_thread(db, last_outbound_is_ai=False, count=1)
    await update_escalation_state(db, lead)
    await db.commit()
    assert lead.ai_miss_count == 0
    assert lead.priority == "normal"


@pytest.mark.asyncio
async def test_first_contact_is_zero(db):
    """Nobody has replied yet, so there is no miss to count."""
    from app.modules.channels.meta.lead_escalation import update_escalation_state

    lead = await _seed_thread(db, last_outbound_is_ai=None, count=1)
    await update_escalation_state(db, lead)
    await db.commit()
    assert lead.ai_miss_count == 0


@pytest.mark.asyncio
async def test_priority_escalates_at_three(db):
    from app.modules.channels.meta.lead_escalation import update_escalation_state

    lead = await _seed_thread(db, last_outbound_is_ai=True, count=3)
    lead.ai_miss_count = 2
    await db.commit()

    await update_escalation_state(db, lead)
    await db.commit()
    assert lead.ai_miss_count == 3
    assert lead.priority == "important"
    assert lead.priority_since is not None


@pytest.mark.asyncio
async def test_priority_deescalates_and_clears_state(db):
    """Counter falls -> priority follows, and all four timestamps clear.

    Without the clearing, a lead that de-escalates and later becomes
    important again would find escalation_reminder_at IS NULL and silently
    receive no second email -- the sweep would read it as already handled.
    """
    from app.modules.channels.meta.lead_escalation import update_escalation_state

    lead = await _seed_thread(db, last_outbound_is_ai=True, count=3)
    lead.ai_miss_count = 2
    await db.commit()
    await update_escalation_state(db, lead)
    await db.commit()
    assert lead.priority == "important"
    lead.escalated_at = datetime.now(timezone.utc)
    lead.escalation_reminder_at = datetime.now(timezone.utc) + timedelta(hours=4)
    lead.handover_sent_at = datetime.now(timezone.utc)
    await db.commit()

    lead.ai_miss_count = 0
    await update_escalation_state(db, lead)
    await db.commit()

    assert lead.priority == "normal"
    assert lead.priority_since is None
    assert lead.escalated_at is None
    assert lead.escalation_reminder_at is None
    assert lead.handover_sent_at is None


@pytest.mark.asyncio
async def test_recipients_default_to_owner_signup_email(db):
    """With no configured list, escalation goes to whoever signed up.

    Lead.tenant_id IS the owner's User.id, so this is a guaranteed-existing
    row -- escalation works on day one with zero configuration.
    """
    from app.modules.channels.meta import lead_escalation

    lead, _ = await _seed_lead(db)
    recipients = await lead_escalation.resolve_recipients(db, lead)
    assert recipients == [f"{lead.tenant_id}@example.com"]


@pytest.mark.asyncio
async def test_recipients_prefer_configured_list(db):
    from app.modules.channels.meta import lead_escalation

    lead, _ = await _seed_lead(db)
    u = await db.get(User, lead.tenant_id)
    u.lead_settings = {"escalation_emails": ["Sales@Example.com", " owner@x.com "]}
    await db.commit()

    recipients = await lead_escalation.resolve_recipients(db, lead)
    # Sorted + de-duplicated for determinism, matching normalize_lead_settings.
    assert recipients == ["owner@x.com", "sales@example.com"]


@pytest.mark.asyncio
async def test_escalation_email_sends_once_and_arms_reminder(db, monkeypatch):
    from app.modules.channels.meta import lead_escalation

    sent: list[dict] = []

    async def _fake(to, subject, message, cta_url=None):
        sent.append({"to": to, "subject": subject, "cta": cta_url})
        return "msg-1"

    monkeypatch.setattr(lead_escalation, "_send_email", _fake)

    lead = await _seed_thread(db, last_outbound_is_ai=True, count=3)
    lead.ai_miss_count = 2
    await db.commit()
    await lead_escalation.update_escalation_state(db, lead)
    await db.commit()

    assert len(sent) == 1
    assert sent[0]["to"] == [f"{lead.tenant_id}@example.com"]
    assert lead.escalated_at is not None
    assert lead.escalation_reminder_at is not None
    assert "channel=" in (sent[0]["cta"] or "")

    # A second update at the same count must not re-send: already important.
    await lead_escalation.update_escalation_state(db, lead)
    await db.commit()
    assert len(sent) == 1, "must not re-send while already escalated"


@pytest.mark.asyncio
async def test_escalation_email_failure_leaves_escalated_at_null(db, monkeypatch):
    """If the provider rejects, the sweep must retry rather than assume a
    human was told."""
    from app.modules.channels.meta import lead_escalation

    async def _boom(*a, **kw):
        raise RuntimeError("resend 429")

    monkeypatch.setattr(lead_escalation, "_send_email", _boom)

    lead = await _seed_thread(db, last_outbound_is_ai=True, count=3)
    lead.ai_miss_count = 2
    await db.commit()
    await lead_escalation.update_escalation_state(db, lead)
    await db.commit()

    assert lead.priority == "important"
    assert lead.escalated_at is None
    assert lead.escalation_reminder_at is None

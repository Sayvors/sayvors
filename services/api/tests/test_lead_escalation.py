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

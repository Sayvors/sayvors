"""Conversation mode: the single authoritative AI/human switch.

See readiness-report §17, HAND-8. The behaviour under test is what the old
design could not express: a human takes a thread over explicitly, the AI stops
for that thread only, and the automatic resume sweep never steals it back.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.modules.channels.models import Channel, ChannelMessage, ChannelThread, Lead
from app.modules.users.models import User

QUIET_OFF = {"quiet_start_hour": 0, "quiet_end_hour": 0}
CUSTOMER = "+966500000001"


async def _noop_async(*args, **kwargs):
    return None


class _NoAdapter:
    async def send_text_message(self, *args, **kwargs):
        return "wamp-1"


async def _seed(db, *, priority: str = "normal"):
    uid = f"mode-user-{uuid.uuid4().hex[:8]}"
    db.add(User(
        id=uid, first_name="M", last_name="A",
        email=f"{uid}@example.com", password_hash="x",
        lead_settings=dict(QUIET_OFF),
    ))
    channel = Channel(
        id=f"mode-chan-{uuid.uuid4().hex[:8]}", user_id=uid,
        platform="whatsapp", platform_user_id="+15550000009",
        display_name="Mode", status="active",
    )
    db.add(channel)
    await db.flush()
    lead = Lead(
        id=f"mode-lead-{uuid.uuid4().hex[:8]}", tenant_id=uid,
        channel_id=channel.id, platform="whatsapp", contact_id=CUSTOMER,
        stage="qualified", language="en", opt_out=False,
        thread_key=CUSTOMER, priority=priority, ai_miss_count=0,
    )
    db.add(lead)
    await db.commit()
    return lead, channel


async def _thread(db, channel):
    return (
        await db.execute(
            select(ChannelThread).where(ChannelThread.channel_id == channel.id)
        )
    ).scalar_one_or_none()


@pytest.mark.asyncio
async def test_human_mode_mutes_the_ai_and_clears_the_clock(db):
    from app.modules.channels.conversation_mode import MODE_HUMAN, get_mode, set_mode
    from app.modules.channels.meta.lead_escalation import should_ai_reply

    lead, channel = await _seed(db, priority="important")
    lead.priority_since = datetime.now(timezone.utc) - timedelta(hours=2)
    lead.escalation_reminder_at = datetime.now(timezone.utc)
    lead.ai_miss_count = 3
    await db.commit()

    await set_mode(
        db, tenant_id=lead.tenant_id, channel_id=channel.id,
        contact_phone=CUSTOMER, mode=MODE_HUMAN, by="user-123",
        reason="manual",
    )

    assert await get_mode(db, channel.id, CUSTOMER) == MODE_HUMAN
    thread = await _thread(db, channel)
    assert thread.mode_changed_by == "user-123"

    await db.refresh(lead)
    assert lead.ai_miss_count == 0, "a takeover starts a fresh miss cycle"
    assert lead.priority == "normal"
    assert lead.priority_since is None, "no escalation clock while a human owns it"
    assert lead.escalation_reminder_at is None
    assert should_ai_reply(lead, mode=MODE_HUMAN) is False


@pytest.mark.asyncio
async def test_ai_mode_hands_the_thread_back_with_a_clean_counter(db):
    from app.modules.channels.conversation_mode import MODE_AI, MODE_HUMAN, set_mode
    from app.modules.channels.meta.lead_escalation import should_ai_reply

    lead, channel = await _seed(db, priority="important")
    lead.ai_miss_count = 3
    lead.priority_since = datetime.now(timezone.utc) - timedelta(hours=25)
    await db.commit()
    await set_mode(
        db, tenant_id=lead.tenant_id, channel_id=channel.id,
        contact_phone=CUSTOMER, mode=MODE_HUMAN, by="user-123",
        reason="manual",
    )

    await set_mode(
        db, tenant_id=lead.tenant_id, channel_id=channel.id,
        contact_phone=CUSTOMER, mode=MODE_AI, by="user-123", reason="resolve",
    )

    await db.refresh(lead)
    assert lead.priority == "normal"
    assert lead.ai_miss_count == 0
    assert lead.priority_since is None
    assert should_ai_reply(lead, mode=MODE_AI) is True


@pytest.mark.asyncio
async def test_reasserting_the_same_mode_is_not_a_transition(db):
    from app.modules.channels.conversation_mode import MODE_HUMAN, set_mode

    lead, channel = await _seed(db)
    await set_mode(
        db, tenant_id=lead.tenant_id, channel_id=channel.id,
        contact_phone=CUSTOMER, mode=MODE_HUMAN, by="user-123", reason="manual",
    )
    first = (await _thread(db, channel)).mode_changed_at

    await set_mode(
        db, tenant_id=lead.tenant_id, channel_id=channel.id,
        contact_phone=CUSTOMER, mode=MODE_HUMAN, by="user-999", reason="manual",
    )
    second = (await _thread(db, channel)).mode_changed_at
    assert first == second, "an idempotent switch must not rewrite the clock"


@pytest.mark.asyncio
async def test_a_human_reply_claims_an_auto_escalated_thread(db):
    """Replying inside an escalated thread moves ownership to the human.

    Without the promotion the thread would still read ``mode_changed_by =
    "system"`` and the resume sweep would hand it back to the AI while the
    agent is typing.
    """
    from app.modules.channels.conversation_mode import (
        MODE_HUMAN,
        MODE_SOURCE_SYSTEM,
        set_mode,
    )

    lead, channel = await _seed(db)
    await set_mode(
        db, tenant_id=lead.tenant_id, channel_id=channel.id,
        contact_phone=CUSTOMER, mode=MODE_HUMAN, by=MODE_SOURCE_SYSTEM,
        reason="escalation",
    )
    assert (await _thread(db, channel)).mode_changed_by == MODE_SOURCE_SYSTEM

    await set_mode(
        db, tenant_id=lead.tenant_id, channel_id=channel.id,
        contact_phone=CUSTOMER, mode=MODE_HUMAN, by="user-123",
        reason="human_reply",
    )
    thread = await _thread(db, channel)
    assert thread.mode_changed_by == "user-123"
    assert thread.conversation_mode == MODE_HUMAN


@pytest.mark.asyncio
async def test_should_ai_reply_keeps_both_guards(db):
    """Priority stays a guard even if the thread-row write was lost."""
    from app.modules.channels.conversation_mode import MODE_AI
    from app.modules.channels.meta.lead_escalation import should_ai_reply

    lead, _ = await _seed(db, priority="important")
    assert should_ai_reply(lead, mode=MODE_AI) is False
    lead.priority = "normal"
    assert should_ai_reply(lead, mode=MODE_AI) is True


@pytest.mark.asyncio
async def test_escalation_sets_human_mode_as_the_system(db, monkeypatch):
    from app.modules.channels.conversation_mode import get_mode
    from app.modules.channels.meta import lead_escalation

    monkeypatch.setattr(lead_escalation, "_send_email", _noop_async)
    lead, channel = await _seed(db, priority="important")

    await lead_escalation.escalate_to_human(
        db, lead, _NoAdapter(), "PNID", "tok"
    )
    await db.commit()

    assert await get_mode(db, channel.id, CUSTOMER) == "human"
    thread = await _thread(db, channel)
    assert thread.mode_changed_by == "system"


@pytest.mark.asyncio
async def test_resume_sweep_leaves_an_explicit_human_takeover_alone(db, monkeypatch):
    """A thread a person took over must never be auto-resumed."""
    from app.modules.channels.conversation_mode import MODE_HUMAN, set_mode
    from app.modules.channels.meta import lead_escalation

    monkeypatch.setattr(lead_escalation, "_send_email", _noop_async)
    lead, channel = await _seed(db, priority="important")
    lead.priority_since = datetime.now(timezone.utc) - timedelta(hours=48)
    lead.ai_miss_count = 3
    await db.commit()
    await set_mode(
        db, tenant_id=lead.tenant_id, channel_id=channel.id,
        contact_phone=CUSTOMER, mode=MODE_HUMAN, by="user-123", reason="manual",
    )
    # Re-arm the clock the way a failed clear would, to prove the sweep guard
    # holds on its own and not only because the clear happened to run.
    lead.priority = "important"
    lead.priority_since = datetime.now(timezone.utc) - timedelta(hours=48)
    await db.commit()

    assert await lead_escalation.run_resume_sweep(db) == 0
    await db.refresh(lead)
    assert lead.priority == "important", "the human keeps the thread"
    assert await _mode(db, channel) == MODE_HUMAN


@pytest.mark.asyncio
async def test_resume_sweep_resumes_a_system_escalation_and_sets_ai_mode(db, monkeypatch):
    from app.modules.channels.conversation_mode import (
        MODE_HUMAN,
        MODE_SOURCE_SYSTEM,
        set_mode,
    )
    from app.modules.channels.meta import lead_escalation

    monkeypatch.setattr(lead_escalation, "_send_email", _noop_async)
    lead, channel = await _seed(db, priority="important")
    lead.priority_since = datetime.now(timezone.utc) - timedelta(hours=48)
    lead.ai_miss_count = 3
    await db.commit()
    await set_mode(
        db, tenant_id=lead.tenant_id, channel_id=channel.id,
        contact_phone=CUSTOMER, mode=MODE_HUMAN, by=MODE_SOURCE_SYSTEM,
        reason="escalation",
    )

    assert await lead_escalation.run_resume_sweep(db) == 1
    await db.commit()
    await db.refresh(lead)
    assert lead.priority == "normal"
    assert await _mode(db, channel) == "ai"


async def _mode(db, channel) -> str:
    from app.modules.channels.conversation_mode import get_mode

    return await get_mode(db, channel.id, CUSTOMER)


@pytest.mark.asyncio
async def test_resolve_clears_a_legacy_escalation_without_a_mode_change(db):
    """Resolve must be restorative even when the thread already reads as AI.

    Deploying the mode column backfilled every thread to 'ai', including ones
    that were escalated and muted. Resolve used to early-return on the unchanged
    mode, leaving priority=important armed — the customer's next message then
    re-escalated instantly, which looked like "resolved, then escalated again".
    """
    from app.modules.channels.conversation_mode import MODE_AI, resolve

    lead, channel = await _seed(db, priority="important")
    lead.ai_miss_count = 3
    lead.priority_since = datetime.now(timezone.utc) - timedelta(hours=2)
    lead.handover_sent_at = datetime.now(timezone.utc)
    thread = await _thread(db, channel)
    assert thread is None, "no thread row yet: the migration default is the case under test"

    await resolve(
        db, tenant_id=lead.tenant_id, channel_id=channel.id,
        contact_phone=CUSTOMER, user_id="user-123",
    )

    await db.refresh(lead)
    assert lead.priority == "normal"
    assert lead.ai_miss_count == 0
    assert lead.priority_since is None
    assert lead.handover_sent_at is None
    assert await _mode(db, channel) == MODE_AI


@pytest.mark.asyncio
async def test_resolve_is_idempotent(db):
    """A second Resolve click must not fail or rewrite the transition time."""
    from app.modules.channels.conversation_mode import resolve

    lead, channel = await _seed(db)
    await resolve(
        db, tenant_id=lead.tenant_id, channel_id=channel.id,
        contact_phone=CUSTOMER, user_id="user-123",
    )
    first = (await _thread(db, channel)).mode_changed_at
    await resolve(
        db, tenant_id=lead.tenant_id, channel_id=channel.id,
        contact_phone=CUSTOMER, user_id="user-123",
    )
    assert (await _thread(db, channel)).mode_changed_at == first


@pytest.mark.asyncio
async def test_a_human_outbound_message_switches_the_thread(db, monkeypatch):
    """Sending from the inbox is what "a human owns this" means in practice."""
    from app.modules.channels import service as channel_service
    from app.modules.channels.conversation_mode import MODE_HUMAN, get_mode
    from app.modules.channels.schemas import ChannelMessageSend

    lead, channel = await _seed(db)
    user = await db.get(User, lead.tenant_id)

    async def _fake_dispatch(db_, user_, channel_, to, text):
        return "wamid-human-1", ""

    monkeypatch.setattr(channel_service, "_dispatch_whatsapp", _fake_dispatch)

    msg = await channel_service.send_message(
        channel.id,
        ChannelMessageSend(
            content="Hi, this is Sara — I'll take it from here.",
            content_type="text",
            contact_phone=CUSTOMER,
        ),
        user,
        db,
    )

    assert msg.status == "sent"
    assert msg.handled_by == "human"
    assert await get_mode(db, channel.id, CUSTOMER) == MODE_HUMAN


@pytest.mark.asyncio
async def test_a_failed_human_send_does_not_mute_the_ai(db, monkeypatch):
    """The customer never saw a human reply, so the AI must keep answering."""
    from app.modules.channels import service as channel_service
    from app.modules.channels.schemas import ChannelMessageSend

    lead, channel = await _seed(db)
    user = await db.get(User, lead.tenant_id)

    async def _failing_dispatch(db_, user_, channel_, to, text):
        return "", "outside the 24h window"

    monkeypatch.setattr(channel_service, "_dispatch_whatsapp", _failing_dispatch)

    msg = await channel_service.send_message(
        channel.id,
        ChannelMessageSend(
            content="too late", content_type="text", contact_phone=CUSTOMER,
        ),
        user,
        db,
    )

    assert msg.status == "failed"
    assert await _mode(db, channel) == "ai"


@pytest.mark.asyncio
async def test_thread_payload_carries_the_mode(db):
    """The inbox list must expose the mode, or the switch has nothing to show."""
    from app.modules.channels.conversation_mode import MODE_HUMAN, set_mode
    from app.modules.channels.service import hash_contact_phone, list_inbox_threads

    lead, channel = await _seed(db)
    user = await db.get(User, lead.tenant_id)
    db.add(ChannelMessage(
        id=str(uuid.uuid4()), channel_id=channel.id, direction="inbound",
        content="hello", content_type="text", status="delivered",
        contact_phone=CUSTOMER,
        contact_phone_hash=hash_contact_phone(CUSTOMER),
    ))
    await db.commit()
    await set_mode(
        db, tenant_id=lead.tenant_id, channel_id=channel.id,
        contact_phone=CUSTOMER, mode=MODE_HUMAN, by="user-123", reason="manual",
    )

    threads = await list_inbox_threads(user, db)
    match = [t for t in threads if t["channel_id"] == channel.id]
    assert match, "the seeded thread must be listed"
    assert match[0]["mode"] == MODE_HUMAN
    assert match[0]["mode_changed_by"] == "user-123"

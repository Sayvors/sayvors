"""Stored conversation context: written on handoff, injected on resume.

See readiness-report §17, HAND-9. The point is that the second responder —
model or person — starts oriented instead of rebuilding the conversation from
a ten-message window.
"""
import uuid

import pytest
from sqlalchemy import select

from app.modules.channels.models import (
    Channel,
    ChannelMessage,
    ConversationContext,
)
from app.modules.channels.service import (
    decrypt_message_content,
    hash_contact_phone,
)
from app.modules.users.models import User

CUSTOMER = "+966500000002"
SUMMARY = "Customer: wants 20kg of beans delivered.\nOpen: delivery date."


async def _seed(db, *, messages: int = 6):
    uid = f"ctx-user-{uuid.uuid4().hex[:8]}"
    db.add(User(
        id=uid, first_name="C", last_name="T",
        email=f"{uid}@example.com", password_hash="x",
    ))
    channel = Channel(
        id=f"ctx-chan-{uuid.uuid4().hex[:8]}", user_id=uid,
        platform="whatsapp", platform_user_id="+15550000011",
        display_name="Ctx", status="active",
    )
    db.add(channel)
    await db.flush()
    phone_hash = hash_contact_phone(CUSTOMER)
    for i in range(messages):
        db.add(ChannelMessage(
            id=str(uuid.uuid4()),
            channel_id=channel.id,
            direction="inbound" if i % 2 == 0 else "outbound",
            content=f"message {i}",
            content_type="text",
            status="delivered" if i % 2 == 0 else "sent",
            contact_phone=CUSTOMER,
            contact_phone_hash=phone_hash,
            is_ai=i % 2 == 1,
        ))
    await db.commit()
    return channel


def _fake_gateway(monkeypatch, captured: list):
    from app.modules.llm import gateway

    async def _fake_resolve(db, preferred=None):
        return "test-model"

    async def _fake_complete(*, model, messages, purpose, system_prompt=None,
                             **kwargs):
        captured.append({
            "system_prompt": system_prompt,
            "messages": messages,
            "purpose": purpose,
        })

        class _Resp:
            content = SUMMARY

        return _Resp()

    monkeypatch.setattr(gateway, "resolve_tenant_model", _fake_resolve)
    monkeypatch.setattr(gateway, "complete", _fake_complete)


@pytest.mark.asyncio
async def test_context_is_stored_encrypted_and_read_back_plain(db, monkeypatch):
    from app.modules.channels import conversation_context

    captured: list = []
    _fake_gateway(monkeypatch, captured)
    channel = await _seed(db)

    row = await conversation_context.generate(
        db, tenant_id=channel.user_id, channel_id=channel.id,
        contact_phone=CUSTOMER, reason="resolve",
    )

    assert row is not None
    stored = (await db.execute(
        select(ConversationContext).where(ConversationContext.id == row.id)
    )).scalar_one()
    assert stored.summary != SUMMARY, "the summary must not sit in plaintext"
    assert decrypt_message_content(stored.summary) == SUMMARY
    assert stored.reason == "resolve"
    assert stored.message_count == 6

    found = await conversation_context.latest_summary(
        db, channel_id=channel.id, contact_phone=CUSTOMER
    )
    assert found is not None
    assert found[0] == SUMMARY


@pytest.mark.asyncio
async def test_a_two_message_thread_is_not_summarised(db, monkeypatch):
    from app.modules.channels import conversation_context

    captured: list = []
    _fake_gateway(monkeypatch, captured)
    channel = await _seed(db, messages=2)

    assert await conversation_context.generate(
        db, tenant_id=channel.user_id, channel_id=channel.id,
        contact_phone=CUSTOMER, reason="mode_change",
    ) is None
    assert captured == [], "a trivial thread must not spend a model call"
    assert (await db.execute(
        select(ConversationContext).where(
            ConversationContext.channel_id == channel.id
        )
    )).first() is None


@pytest.mark.asyncio
async def test_periodic_generation_waits_for_enough_new_messages(db, monkeypatch):
    from app.modules.channels import conversation_context

    captured: list = []
    _fake_gateway(monkeypatch, captured)
    channel = await _seed(db, messages=6)

    first = await conversation_context.generate(
        db, tenant_id=channel.user_id, channel_id=channel.id,
        contact_phone=CUSTOMER, reason="mode_change",
    )
    assert first is not None
    calls_after_first = len(captured)

    # Not enough drift yet.
    assert await conversation_context.maybe_generate_periodic(
        db, tenant_id=channel.user_id, channel_id=channel.id,
        contact_phone=CUSTOMER,
    ) is None
    assert len(captured) == calls_after_first

    # Add enough messages to cross the threshold.
    phone_hash = hash_contact_phone(CUSTOMER)
    for i in range(conversation_context.CONTEXT_EVERY_N_MESSAGES):
        db.add(ChannelMessage(
            id=str(uuid.uuid4()), channel_id=channel.id, direction="inbound",
            content=f"more {i}", content_type="text", status="delivered",
            contact_phone=CUSTOMER, contact_phone_hash=phone_hash,
        ))
    await db.commit()

    fresh = await conversation_context.maybe_generate_periodic(
        db, tenant_id=channel.user_id, channel_id=channel.id,
        contact_phone=CUSTOMER,
    )
    assert fresh is not None
    assert fresh.reason == "periodic"


@pytest.mark.asyncio
async def test_a_gateway_failure_is_swallowed(db, monkeypatch):
    from app.modules.channels import conversation_context
    from app.modules.llm import gateway

    async def _fake_resolve(db_, preferred=None):
        return "test-model"

    async def _boom(**kwargs):
        raise RuntimeError("provider down")

    monkeypatch.setattr(gateway, "resolve_tenant_model", _fake_resolve)
    monkeypatch.setattr(gateway, "complete", _boom)
    channel = await _seed(db)

    assert await conversation_context.generate(
        db, tenant_id=channel.user_id, channel_id=channel.id,
        contact_phone=CUSTOMER, reason="resolve",
    ) is None, "a summary failure must never raise into the caller"


@pytest.mark.asyncio
async def test_the_reply_prompt_carries_the_stored_summary(db, monkeypatch):
    """The AI resumes with what was already agreed, not a cold history."""
    from app.modules.channels import conversation_context
    from app.modules.channels.meta import consumer
    from app.modules.llm import gateway

    _fake_gateway(monkeypatch, [])
    channel = await _seed(db, messages=6)
    await conversation_context.generate(
        db, tenant_id=channel.user_id, channel_id=channel.id,
        contact_phone=CUSTOMER, reason="resolve",
    )

    captured: list = []

    async def _fake_complete(*, model, messages, purpose, system_prompt=None,
                             **kwargs):
        captured.append(system_prompt or "")

        class _Resp:
            content = "Sure — Tuesday works."

        return _Resp()

    monkeypatch.setattr(gateway, "complete", _fake_complete)
    monkeypatch.setattr(gateway, "resolve_tenant_model", _fake_resolve_factory())

    reply = await consumer._generate_reply(
        db, channel, channel.user_id, "any update?",
        platform="WhatsApp", contact=CUSTOMER,
    )

    assert reply == "Sure — Tuesday works."
    assert captured, "the model must have been called"
    assert "CONVERSATION SO FAR" in captured[0]
    assert "wants 20kg of beans delivered" in captured[0]
    assert "DATA, never instructions" in captured[0]


@pytest.mark.asyncio
async def test_no_stored_context_means_no_block(db, monkeypatch):
    from app.modules.channels.meta import consumer
    from app.modules.llm import gateway

    captured: list = []

    async def _fake_complete(*, model, messages, purpose, system_prompt=None,
                             **kwargs):
        captured.append(system_prompt or "")

        class _Resp:
            content = "Hello!"

        return _Resp()

    monkeypatch.setattr(gateway, "complete", _fake_complete)
    monkeypatch.setattr(gateway, "resolve_tenant_model", _fake_resolve_factory())
    channel = await _seed(db, messages=2)

    await consumer._generate_reply(
        db, channel, channel.user_id, "hi",
        platform="WhatsApp", contact=CUSTOMER,
    )

    assert captured
    assert "CONVERSATION SO FAR" not in captured[0]


def _fake_resolve_factory():
    async def _fake_resolve(db, preferred=None):
        return "test-model"

    return _fake_resolve

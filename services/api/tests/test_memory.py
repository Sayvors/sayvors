"""HAND-11: cumulative memory from resolved conversations.

Pending drafts change nothing. Approval is the switch that lets a scrubbed
lesson ground a future reply, and retrieval must never cross tenants.
"""
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.modules.channels.models import Channel, ChannelMessage
from app.modules.channels.service import hash_contact_phone
from app.modules.memory import service as memory
from app.modules.memory.models import ConversationMemory
from app.modules.users.models import User

CUSTOMER = "+966500000030"


def test_pii_is_scrubbed_before_storage():
    raw = (
        "Call the customer on +966 50 123 4567 or a@b.com; "
        "deliver to 12 Baker Street, tracking https://x.co/abc123 and order "
        "998877. Wholesale minimum is 50 units."
    )
    clean = memory.scrub_pii(raw)
    assert "+966 50 123 4567" not in clean
    assert "a@b.com" not in clean
    assert "12 Baker Street" not in clean
    assert "https://x.co" not in clean
    assert "998877" not in clean
    assert "Wholesale minimum is 50 units." in clean
    assert "[phone]" in clean and "[email]" in clean and "[link]" in clean
    assert "[address]" in clean


@pytest.mark.asyncio
async def test_memory_is_pending_and_deduplicated(db):
    row = await memory.create_memory(
        db,
        tenant_id="mem-tenant",
        channel_id="mem-chan",
        source_context_id=None,
        summary="Customer asked for the wholesale minimum. Call +966500000030.",
        outcome="quote sent",
        facts=["Wholesale minimum is 50 units", "Email sales@example.com"],
    )
    assert row is not None
    assert row.status == "pending", "a draft must never be live"
    assert "+966500000030" not in row.summary
    assert row.facts[0] == "Wholesale minimum is 50 units"
    assert "sales@example.com" not in " ".join(row.facts)
    assert any("[email]" in fact for fact in row.facts)

    duplicate = await memory.create_memory(
        db,
        tenant_id="mem-tenant",
        channel_id="mem-chan",
        source_context_id=None,
        summary="Customer asked for the wholesale minimum. Call +966500000030.",
        outcome="quote sent",
        facts=[],
    )
    assert duplicate is None, "re-resolving the same summary must not queue twice"


@pytest.mark.asyncio
async def test_the_known_customer_name_is_redacted(db):
    row = await memory.create_memory(
        db, tenant_id="mem-name", channel_id="c", source_context_id=None,
        summary="Sara asked for the wholesale minimum.",
        outcome="answered",
        facts=["Sara needs delivery to Riyadh"],
        redact_names=["Sara"],
    )
    assert "Sara" not in row.summary
    assert "Sara" not in " ".join(row.facts)
    assert "[customer]" in row.summary


@pytest.mark.asyncio
async def test_only_approved_memory_is_retrieved_and_tenant_scoped(db):
    pending = await memory.create_memory(
        db, tenant_id="mem-a", channel_id="c1", source_context_id=None,
        summary="Jeddah delivery takes two days.", outcome="answered",
        facts=["Jeddah delivery takes two days"],
    )
    approved = await memory.create_memory(
        db, tenant_id="mem-a", channel_id="c1", source_context_id=None,
        summary="Wholesale minimum is 50 units.", outcome="answered",
        facts=["Wholesale minimum is 50 units"],
        status="approved",
    )
    await memory.create_memory(
        db, tenant_id="mem-b", channel_id="c2", source_context_id=None,
        summary="Wholesale minimum is 900 units.", outcome="answered",
        facts=["Wholesale minimum is 900 units"],
        status="approved",
    )

    block = await memory.reply_block(
        db, tenant_id="mem-a", query="what is the wholesale minimum?", enabled=True
    )
    assert "50 units" in block
    assert "900 units" not in block, "another tenant's memory must never leak"
    assert "Jeddah" not in block, "pending drafts are inert"

    assert (
        await memory.reply_block(
            db, tenant_id="mem-a", query="wholesale minimum", enabled=False
        )
        == ""
    )


@pytest.mark.asyncio
async def test_review_approves_and_reopens(db):
    row = await memory.create_memory(
        db, tenant_id="mem-review", channel_id="c", source_context_id=None,
        summary="Minimum booking is two nights.", outcome="booking confirmed",
        facts=["Minimum booking is two nights"],
    )
    approved = await memory.review_memory(
        db, tenant_id="mem-review", memory_id=row.id, actor_id="reviewer",
        status="approved",
    )
    assert approved.status == "approved"
    assert approved.reviewed_by == "reviewer"
    assert approved.reviewed_at is not None

    reopened = await memory.review_memory(
        db, tenant_id="mem-review", memory_id=row.id, actor_id="reviewer",
        status="pending",
    )
    assert reopened.reviewed_at is None
    assert reopened.reviewed_by is None

    with pytest.raises(ValueError):
        await memory.review_memory(
            db, tenant_id="mem-review", memory_id=row.id, actor_id="x",
            status="published",
        )

    assert await memory.review_memory(
        db, tenant_id="other", memory_id=row.id, actor_id="x", status="approved"
    ) is None


@pytest.mark.asyncio
async def test_capture_from_resolution_respects_the_toggle(
    db, monkeypatch
):
    async def _fake_extract(*args, **kwargs):
        return (
            "Bookings require a two-night minimum.",
            "booking confirmed",
            ["Minimum booking is two nights"],
            "test",
        )

    monkeypatch.setattr(memory, "extract_memory", _fake_extract)

    row = await memory.capture_from_resolution(
        db,
        tenant_id="mem-capture",
        channel_id="c",
        contact_phone=CUSTOMER,
        context=None,
        summary="Customer booked two nights and paid a deposit.",
    )
    assert row is not None
    assert row.status == "pending"
    assert row.outcome == "booking confirmed"
    assert row.facts == ["Minimum booking is two nights"]

    # A tenant that turned memory off gets no draft and no retrieval.
    db.add(User(
        id="mem-off", first_name="M", last_name="Off",
        email="mem-off@example.com", password_hash="x",
        ai_memory_enabled=False,
    ))
    await db.commit()
    assert await memory.capture_from_resolution(
        db, tenant_id="mem-off", channel_id="c", contact_phone=CUSTOMER,
        context=None, summary="Another lesson.",
    ) is None


@pytest.mark.asyncio
async def test_memory_review_api_and_settings(client, db, user_id):
    db.add(User(
        id=user_id, first_name="Memory", last_name="Owner",
        email="memory-owner@example.com", password_hash="x",
    ))
    row = await memory.create_memory(
        db, tenant_id=user_id, channel_id="api-chan", source_context_id=None,
        summary="Delivery within Riyadh is free above 200 SAR.",
        outcome="answered",
        facts=["Delivery within Riyadh is free above 200 SAR"],
    )
    await db.commit()

    listed = client.get("/api/v1/memory?status=pending")
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["pending_count"] == 1
    assert body["memories"][0]["id"] == row.id

    approved = client.patch(
        f"/api/v1/memory/{row.id}", json={"status": "approved"}
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    assert approved.json()["reviewed_by"] == user_id

    settings = client.patch(
        "/api/v1/memory/settings", json={"enabled": False}
    )
    assert settings.status_code == 200, settings.text
    assert settings.json()["enabled"] is False
    assert client.get("/api/v1/memory/settings").json()["enabled"] is False

    bad = client.patch(
        f"/api/v1/memory/{row.id}", json={"status": "published"}
    )
    assert bad.status_code == 422, bad.text


@pytest.mark.asyncio
async def test_the_reply_prompt_carries_approved_memory(db, monkeypatch):
    from app.modules.channels.meta import consumer
    from app.modules.llm import gateway
    from app.modules.profile import business_profile
    from app.modules.rag import grounding
    from app.modules.catalog import service as catalog_service

    uid = f"mem-user-{uuid.uuid4().hex[:8]}"
    db.add(User(
        id=uid, first_name="M", last_name="U",
        email=f"{uid}@example.com", password_hash="x",
        ai_memory_enabled=True,
    ))
    channel = Channel(
        id=f"mem-chan-{uuid.uuid4().hex[:8]}", user_id=uid,
        platform="whatsapp", platform_user_id="pn-mem",
        display_name="Memory", status="active",
    )
    db.add(channel)
    await db.flush()
    for i in range(4):
        db.add(ChannelMessage(
            id=str(uuid.uuid4()), channel_id=channel.id,
            direction="inbound" if i % 2 == 0 else "outbound",
            content="what is the wholesale minimum?" if i == 0 else "ok",
            content_type="text", status="delivered",
            contact_phone=CUSTOMER,
            contact_phone_hash=hash_contact_phone(CUSTOMER),
        ))
    await memory.create_memory(
        db, tenant_id=uid, channel_id=channel.id, source_context_id=None,
        summary="Wholesale buyers must order at least 50 units.",
        outcome="answered",
        facts=["Wholesale minimum is 50 units"],
        status="approved",
    )
    await db.commit()

    captured: list[str] = []

    async def _fake_complete(*, model, messages, purpose, system_prompt=None, **kwargs):
        captured.append(system_prompt or "")

        class _Resp:
            content = "The minimum is 50 units."

        return _Resp()

    async def _fake_resolve(db_, preferred=None):
        return "test-model"

    async def _empty(*args, **kwargs):
        return ""

    monkeypatch.setattr(gateway, "complete", _fake_complete)
    monkeypatch.setattr(gateway, "resolve_tenant_model", _fake_resolve)
    monkeypatch.setattr(business_profile, "prompt_block", _empty)
    monkeypatch.setattr(grounding, "reply_block", _empty)
    monkeypatch.setattr(catalog_service, "catalog_block", _empty)

    reply = await consumer._generate_reply(
        db, channel, uid, "what is the wholesale minimum?",
        platform="WhatsApp", contact=CUSTOMER,
    )
    assert reply == "The minimum is 50 units."
    prompt = captured[0]
    assert "LEARNED FROM EARLIER CONVERSATIONS" in prompt
    assert "Wholesale minimum is 50 units" in prompt

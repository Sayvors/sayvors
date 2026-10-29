"""A quoted handoff code must reach the AI even when the thread is escalated.

Regression guard for BUG-2: the escalation gate returned before the review
handoff lookup, so a customer who quoted a code from a public review reply was
muted together with the rest of the thread. The code is an explicit request
about an existing ticket, not another repeat question.
"""
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.channels.meta import consumer
from app.modules.channels.models import Channel, ChannelMessage, Lead
from app.modules.channels.meta.models import MetaAsset, MetaConnection
from app.modules.users.models import User
from conftest import TEST_ENGINE

QUIET_OFF = {"quiet_start_hour": 0, "quiet_end_hour": 0}
PHONE_NUMBER_ID = "PNID-HANDOFF"
CUSTOMER = "+966500000001"


def _session_factory():
    return async_sessionmaker(TEST_ENGINE, class_=AsyncSession, expire_on_commit=False)


class _Adapter:
    def __init__(self) -> None:
        self.sent: list[str] = []
        self.typing: list[str] = []

    async def send_text_message(self, phone_number_id, token, to, text):
        self.sent.append(text)
        return "wamid-out-1"

    async def send_typing_indicator(self, phone_number_id, token, wamid):
        self.typing.append(wamid)


async def _seed(db):
    uid = f"handoff-user-{uuid.uuid4().hex[:8]}"
    db.add(User(
        id=uid, first_name="Aster", last_name="Coffee",
        email=f"{uid}@example.com", password_hash="x",
        voice_replies="off", response_style="concise",
        lead_settings=dict(QUIET_OFF),
    ))
    conn = MetaConnection(
        id=f"handoff-conn-{uuid.uuid4().hex[:8]}", tenant_id=uid,
        provider="whatsapp", status="active", access_token_encrypted="enc",
    )
    db.add(conn)
    await db.flush()
    db.add(MetaAsset(
        id=f"handoff-asset-{uuid.uuid4().hex[:8]}", tenant_id=uid,
        connection_id=conn.id, provider="whatsapp", asset_type="phone_number",
        external_asset_id=PHONE_NUMBER_ID, active=True,
        phone="+15550000002", status="connected",
    ))
    channel = Channel(
        id=f"handoff-chan-{uuid.uuid4().hex[:8]}", user_id=uid,
        platform="whatsapp", platform_user_id=PHONE_NUMBER_ID,
        display_name="Aster", status="active",
    )
    db.add(channel)
    await db.flush()
    lead = Lead(
        id=f"handoff-lead-{uuid.uuid4().hex[:8]}", tenant_id=uid,
        channel_id=channel.id, platform="whatsapp", contact_id=CUSTOMER,
        contact_name="Luke", stage="qualified", language="en",
        opt_out=False, thread_key=CUSTOMER,
        priority="important", ai_miss_count=3,
        priority_since=datetime.now(timezone.utc) - timedelta(hours=25),
    )
    db.add(lead)
    await db.commit()
    return lead, channel


async def _patch_consumer(
    monkeypatch,
    adapter,
    *,
    generate,
    resolve=None,
) -> None:
    """Wire the consumer to the test session and a fake adapter/model."""

    async def _noop(*args, **kwargs):
        return None

    async def _fake_classify(*args, **kwargs):
        return {"language": "en", "confused": False, "awaiting_user": False}

    async def _fake_render(style, reply, tenant_id, db_):
        return [reply]

    async def _no_match(*args, **kwargs):
        return None

    def _fake_decrypt(connection):
        return "tok"

    monkeypatch.setattr(consumer, "async_session", _session_factory())
    monkeypatch.setattr(consumer, "_typing_indicator_enabled", _noop)
    monkeypatch.setattr(consumer, "_publish_typing", _noop)
    monkeypatch.setattr(consumer, "_publish_message_notification", _noop)
    monkeypatch.setattr(consumer, "_generate_reply", generate)
    monkeypatch.setattr(
        "app.modules.channels.meta.credentials.decrypt_connection_token",
        _fake_decrypt,
    )
    monkeypatch.setattr(
        "app.modules.channels.meta.service.get_adapter", lambda platform: adapter
    )
    monkeypatch.setattr(
        "app.modules.channels.meta.thread_stats.classify_thread", _fake_classify
    )
    monkeypatch.setattr(
        "app.modules.channels.meta.thread_state.apply_classification", _noop
    )
    monkeypatch.setattr(
        "app.modules.channels.realtime.publish_inbox_event", _noop
    )
    monkeypatch.setattr(
        "app.modules.review_engine.handoff.resolve_and_advance",
        resolve or _no_match,
    )
    monkeypatch.setattr(
        "app.modules.review_engine.handoff.is_status_check", lambda text: False
    )
    monkeypatch.setattr(
        "app.modules.channels.meta.response_style.render_response", _fake_render
    )


@pytest.mark.asyncio
async def test_handoff_code_reaches_ai_while_escalated(db, monkeypatch):
    lead, channel = await _seed(db)
    adapter = _Adapter()

    async def _fake_generate(*args, **kwargs):
        return "Your issue is resolved — the replacement ships today."

    async def _fake_resolve(*args, **kwargs):
        return SimpleNamespace(
            issue=SimpleNamespace(
                ticket_number="T-1042",
                status="open",
                priority="high",
                primary_category="order",
                subcategory=None,
                subcategory_detail=None,
                intent="replacement",
                sentiment="negative",
                summary="Order never arrived.",
                review_text="Still waiting on my order.",
            ),
            matched_by="code",
            raw="GFW8XH",
        )

    await _patch_consumer(
        monkeypatch, adapter, generate=_fake_generate, resolve=_fake_resolve
    )

    event = {
        "external_asset_id": PHONE_NUMBER_ID,
        "external_event_id": "wamid-in-handoff-1",
        "occurred_at": datetime.now(timezone.utc).isoformat(),
    }
    data = {"from": CUSTOMER, "text": "GFW8XH", "msg_type": "text"}

    await consumer._handle_message_received(event, data)

    # The consumer wrote through its own session; reload before asserting.
    await db.refresh(lead)
    refreshed = (await db.execute(
        select(Lead).where(Lead.id == lead.id)
    )).scalar_one()
    assert adapter.sent == [
        "Your issue is resolved — the replacement ships today."
    ], "the code must get an AI reply, not the handover line"
    assert refreshed.priority == "normal", "the code must hand the thread back"
    assert refreshed.ai_miss_count == 0

    handovers = (await db.execute(
        select(ChannelMessage).where(
            ChannelMessage.channel_id == channel.id,
            ChannelMessage.handled_by == "system",
        )
    )).scalars().all()
    assert handovers == [], "a matched code must not trigger the handover mute"


@pytest.mark.asyncio
async def test_a_human_owned_thread_gets_no_ai_reply_and_no_holding_line(
    db, monkeypatch
):
    """Explicit human mode means silence — not the escalation holding line.

    The holding line is the automatic escalation's way of explaining why the
    AI stopped. When a person already owns the thread, sending it would be
    false and would put an AI-pipeline message into a human conversation.
    """
    from app.modules.channels.conversation_mode import MODE_HUMAN, set_mode

    lead, channel = await _seed(db)
    lead.priority = "normal"
    lead.ai_miss_count = 0
    await db.commit()
    await set_mode(
        db, tenant_id=lead.tenant_id, channel_id=channel.id,
        contact_phone=CUSTOMER, mode=MODE_HUMAN, by="user-123", reason="manual",
    )
    adapter = _Adapter()

    async def _fake_generate(*args, **kwargs):
        raise AssertionError("the AI must not generate in human mode")

    await _patch_consumer(monkeypatch, adapter, generate=_fake_generate)

    event = {
        "external_asset_id": PHONE_NUMBER_ID,
        "external_event_id": "wamid-in-human-1",
        "occurred_at": datetime.now(timezone.utc).isoformat(),
    }
    data = {"from": CUSTOMER, "text": "any update?", "msg_type": "text"}

    await consumer._handle_message_received(event, data)

    assert adapter.sent == [], "a human-owned thread must stay silent"
    assert adapter.typing == [], "no typing indicator for a muted thread"
    handovers = (await db.execute(
        select(ChannelMessage).where(
            ChannelMessage.channel_id == channel.id,
            ChannelMessage.handled_by == "system",
        )
    )).scalars().all()
    assert handovers == [], "no holding line for a human-owned thread"

"""Instagram DM messaging: parser mids, consumer pipeline, manual sends,
webhook subscription.

The basic IG loop: a DM to the connected IG professional account is stored,
an AI reply is generated and sent through the PARENT FACEBOOK PAGE's token
(IG messaging rides page-linked messaging — the IG connection holds no
usable messaging credential), and the inbox can send manually the same way.
The WhatsApp branch is untouched; these tests pin that nothing it needs
changed either.
"""
import json
import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from unittest.mock import AsyncMock

from conftest import TEST_ENGINE

from app.modules.channels import service as _channel_service
from app.modules.channels.meta import consumer as _consumer
from app.modules.channels.meta import service as _meta_service
from app.modules.channels.meta.models import MetaAsset, MetaConnection
from app.modules.channels.meta.providers import instagram as _ig
from app.modules.channels.meta.providers.base import MetaAPIError
from app.modules.channels.meta.providers.facebook import FacebookAdapter
from app.modules.channels.meta.webhooks.parser import parse
from app.modules.channels.models import Channel, ChannelMessage
from app.modules.channels.schemas import ChannelMessageSend

TENANT = "ig-tenant-0000-0000-0000-000000000001"
PAGE_ID = "page-111111"
PAGE_TOKEN = "page-token-xyz"
IG_ID = "ig-17841400000000001"
IGSID = "1234567890"
MID = "ig_mid_test_0001"
REPLY = "Yes, we deliver! Which area are you in?"


def _test_session_factory():
    """Session factory bound to the test engine (consumer opens its own)."""
    return async_sessionmaker(TEST_ENGINE, class_=AsyncSession, expire_on_commit=False)


class _Mocks:
    pass


@pytest.fixture
def ig_mocks(monkeypatch):
    """The consumer runs for real; only Graph is mocked."""
    monkeypatch.setattr(_consumer, "async_session", _test_session_factory())
    m = _Mocks()
    m.send = AsyncMock(return_value="IgMsgProvider-1")
    m.typing = AsyncMock(return_value=True)
    m.profile = AsyncMock(return_value={"name": "Sara", "username": "sara_ig"})
    m.reply = AsyncMock(return_value=REPLY)
    monkeypatch.setattr(_ig.InstagramAdapter, "send_text_message", m.send)
    monkeypatch.setattr(_ig.InstagramAdapter, "send_typing_indicator", m.typing)
    monkeypatch.setattr(_ig.InstagramAdapter, "get_contact_profile", m.profile)
    monkeypatch.setattr(_consumer, "_generate_reply", m.reply)
    return m


async def _seed_ig_stack(db, with_page_token=True):
    """Connection + parent Page (+token) + IG account under the parent."""
    conn = MetaConnection(
        id=str(uuid.uuid4()), tenant_id=TENANT, provider="instagram",
        access_token_encrypted="x", status="active", connection_type="oauth",
    )
    page = MetaAsset(
        id=str(uuid.uuid4()), tenant_id=TENANT, connection_id=conn.id,
        provider="facebook", asset_type="page", external_asset_id=PAGE_ID,
        name="Test Page", active=True,
        asset_metadata={"page_access_token": PAGE_TOKEN} if with_page_token else {},
    )
    ig = MetaAsset(
        id=str(uuid.uuid4()), tenant_id=TENANT, connection_id=conn.id,
        provider="instagram", asset_type="ig_account", external_asset_id=IG_ID,
        username="myshop", parent_asset_id=page.id, active=True,
    )
    db.add_all([conn, page, ig])
    await db.commit()
    return conn, page, ig


async def _seed_channel(db, platform_user_id=IG_ID):
    channel = Channel(
        id=str(uuid.uuid4()), user_id=TENANT, platform="instagram",
        platform_user_id=platform_user_id, display_name="myshop",
        status="active",
    )
    db.add(channel)
    await db.commit()
    return channel


def _dm_bytes(field="messages", raw=None, mid=MID, provider="instagram",
              asset_id=IG_ID):
    """The envelope _process_message consumes (what the outbox ships)."""
    if raw is None:
        raw = {
            "sender": {"id": IGSID},
            "recipient": {"id": IG_ID},
            "timestamp": "2026-10-04T00:00:00+00:00",
            "message": {"mid": mid, "text": "do you deliver to Maadi?"},
        }
    envelope = {
        "provider": provider,
        "external_asset_id": asset_id,
        "external_event_id": mid,
        "event_type": "message.received",
        "occurred_at": "2026-10-04T00:00:00+00:00",
        "payload": {"field": field, "raw": raw},
    }
    return json.dumps(envelope).encode("utf-8")


async def _messages(db):
    return (await db.execute(
        select(ChannelMessage).order_by(ChannelMessage.created_at)
    )).scalars().all()


# ── Parser: the mid lives at value.message.mid ───────────


def test_parse_instagram_message_uses_nested_mid():
    payload = {
        "object": "instagram",
        "entry": [{
            "id": IG_ID,
            "time": 1759500000,
            "changes": [{
                "field": "messages",
                "value": {
                    "sender": {"id": IGSID},
                    "recipient": {"id": IG_ID},
                    "timestamp": 1759500000,
                    "message": {"mid": MID, "text": "hello"},
                },
            }],
        }],
    }
    provider, events = parse(payload)
    assert provider == "instagram"
    assert len(events) == 1
    ev = events[0]
    assert ev["external_asset_id"] == IG_ID
    # A stable mid is what makes consumer replay dedupe work — a time-based
    # synthetic id would store every redelivery twice.
    assert ev["external_event_id"] == MID
    assert ev["event_type"] == "message.received"
    assert ev["data"]["field"] == "messages"


def test_parse_instagram_without_mid_falls_back_synthetic():
    payload = {
        "object": "instagram",
        "entry": [{
            "id": IG_ID,
            "time": 1759500000,
            "changes": [{"field": "messages", "value": {"foo": "bar"}}],
        }],
    }
    _, events = parse(payload)
    assert len(events) == 1
    assert events[0]["external_event_id"].startswith("messages-")


def test_parse_page_message_uses_nested_mid():
    """Same mid bug lived in the page parser (Messenger shares the shape)."""
    payload = {
        "object": "page",
        "entry": [{
            "id": PAGE_ID,
            "time": 1759500000,
            "changes": [{
                "field": "messages",
                "value": {"message": {"mid": "pg_mid_1", "text": "hi"}},
            }],
        }],
    }
    provider, events = parse(payload)
    assert provider == "facebook"
    assert events[0]["external_event_id"] == "pg_mid_1"


def test_parse_instagram_messaging_array():
    """Page-linked IG accounts deliver DMs on a top-level entry `messaging`
    array — no changes/field wrapper. The changes-shape parser read ZERO
    events from real Meta payloads, so DMs silently 200'd into nothing.
    (Body captured verbatim from a real webhook.)"""
    payload = {
        "object": "instagram",
        "entry": [{
            "time": 1791188359762,
            "id": IG_ID,
            "messaging": [{
                "sender": {"id": "1560689862767193"},
                "recipient": {"id": IG_ID},
                "timestamp": 1791188359047,
                "message": {"mid": "aWdfZAG1faXRlbTox", "text": "Hi"},
            }],
        }],
    }
    provider, events = parse(payload)
    assert provider == "instagram"
    assert len(events) == 1
    ev = events[0]
    assert ev["external_asset_id"] == IG_ID
    assert ev["external_event_id"] == "aWdfZAG1faXRlbTox"
    assert ev["data"]["field"] == "messages"
    assert ev["data"]["raw"]["sender"]["id"] == "1560689862767193"
    assert ev["data"]["raw"]["message"]["text"] == "Hi"


def test_parse_instagram_messaging_skips_read_receipts():
    """Entries without a message (reads/deliveries) are history only — they
    must not produce a message event."""
    payload = {
        "object": "instagram",
        "entry": [{
            "id": IG_ID,
            "messaging": [
                {"sender": {"id": "1"}, "recipient": {"id": IG_ID},
                 "timestamp": 1791188359047, "read": {"mid": "x"}},
            ],
        }],
    }
    _, events = parse(payload)
    assert events == []


# ── Consumer: DM in → row + AI reply through the Page ─────


@pytest.mark.asyncio
async def test_instagram_inbound_stored_and_ai_reply_sent(db, ig_mocks):
    await _seed_ig_stack(db)
    await _consumer._process_message(_dm_bytes())

    rows = await _messages(db)
    inbound = [r for r in rows if r.direction == "inbound"]
    outbound = [r for r in rows if r.direction == "outbound"]
    assert len(inbound) == 1 and len(outbound) == 1
    assert inbound[0].platform_message_id == MID
    # The thread is keyed on the IGSID (contact_phone is String(32) — fits).
    assert inbound[0].contact_phone == IGSID
    assert inbound[0].content == "do you deliver to Maadi?"
    # Best-effort profile read names the contact for the inbox.
    assert inbound[0].contact_name == "Sara"
    ig_mocks.profile.assert_awaited_once_with(PAGE_TOKEN, IGSID)
    assert outbound[0].status == "sent"
    assert outbound[0].contact_phone == IGSID
    # The send rides the parent Page's id + token, recipient = the customer.
    ig_mocks.send.assert_called_once_with(PAGE_ID, PAGE_TOKEN, IGSID, REPLY)
    ig_mocks.typing.assert_called_once_with(PAGE_ID, PAGE_TOKEN, IGSID)
    assert ig_mocks.reply.await_args.kwargs.get("platform") == "Instagram"
    # Channel get-or-created for the IG account, named after the handle.
    channel = (await db.execute(
        select(Channel).where(Channel.platform == "instagram")
    )).scalar_one()
    assert channel.platform_user_id == IG_ID
    assert channel.display_name == "myshop"


@pytest.mark.asyncio
async def test_contact_profile_cached_with_avatar(db, ig_mocks):
    """name/username/profile_pic land in contact_profiles; a follow-up
    message within the freshness window skips the Graph read."""
    from app.modules.channels.models import ContactProfile

    await _seed_ig_stack(db)
    # The fixture's mock is bound to the adapter class — mutate it in place.
    ig_mocks.profile.return_value = {
        "name": "Aisha",
        "username": "aisha_ig",
        "profile_pic": "https://cdn.example/aisha.jpg",
    }
    await _consumer._process_message(_dm_bytes())

    row = (await db.execute(
        select(ContactProfile).where(ContactProfile.platform == "instagram")
    )).scalar_one()
    assert row.tenant_id == TENANT
    assert row.contact_id == IGSID
    assert row.name == "Aisha"
    assert row.username == "aisha_ig"
    assert row.avatar_url == "https://cdn.example/aisha.jpg"
    assert row.profile_fetched_at is not None
    assert ig_mocks.profile.await_count == 1

    # The cache is fresh — the next message must not re-read the profile.
    await _consumer._process_message(_dm_bytes(mid="mid_2", raw={
        "sender": {"id": IGSID},
        "recipient": {"id": IG_ID},
        "timestamp": "2026-10-04T00:01:00+00:00",
        "message": {"mid": "mid_2", "text": "second dm"},
    }))
    assert ig_mocks.profile.await_count == 1


@pytest.mark.asyncio
async def test_instagram_redelivery_is_idempotent(db, ig_mocks):
    await _seed_ig_stack(db)
    event = _dm_bytes()
    await _consumer._process_message(event)
    await _consumer._process_message(event)  # Kafka redelivery / outbox replay

    rows = await _messages(db)
    assert len([r for r in rows if r.direction == "inbound"]) == 1
    assert len([r for r in rows if r.direction == "outbound"]) == 1
    assert ig_mocks.send.await_count == 1


@pytest.mark.asyncio
async def test_instagram_echo_stored_outbound_without_reply(db, ig_mocks):
    """Meta never echoes the app's own API sends back — is_echo means a
    human replied on another surface. History, not a trigger."""
    await _seed_ig_stack(db)
    raw = {
        "sender": {"id": IG_ID},      # merchant is the sender on an echo
        "recipient": {"id": IGSID},   # the customer is the recipient
        "message": {"mid": MID, "text": "Sent from the Meta inbox", "is_echo": True},
    }
    await _consumer._process_message(_dm_bytes(raw=raw))

    rows = await _messages(db)
    inbound = [r for r in rows if r.direction == "inbound"]
    outbound = [r for r in rows if r.direction == "outbound"]
    assert len(inbound) == 0 and len(outbound) == 1
    # The thread is keyed on the customer either way.
    assert outbound[0].contact_phone == IGSID
    assert outbound[0].content == "Sent from the Meta inbox"
    assert outbound[0].status == "sent"
    ig_mocks.reply.assert_not_awaited()
    ig_mocks.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_instagram_standby_and_handovers_ignored(db, ig_mocks):
    """standby / messaging_handovers share the sender+message shape but mean
    a human agent owns the thread — the AI must never answer them."""
    await _seed_ig_stack(db)
    for field in ("standby", "messaging_handovers"):
        await _consumer._process_message(_dm_bytes(field=field))

    assert await _messages(db) == []
    ig_mocks.reply.assert_not_awaited()
    ig_mocks.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_instagram_send_failure_records_failed_row(db, ig_mocks):
    await _seed_ig_stack(db)
    ig_mocks.send.side_effect = MetaAPIError("(#10)Recipient not found", 400)
    await _consumer._process_message(_dm_bytes())

    rows = await _messages(db)
    inbound = [r for r in rows if r.direction == "inbound"]
    outbound = [r for r in rows if r.direction == "outbound"]
    # The DM is still stored — only the reply failed.
    assert len(inbound) == 1 and len(outbound) == 1
    assert outbound[0].status == "failed"
    assert "Recipient not found" in (outbound[0].error or "")


@pytest.mark.asyncio
async def test_instagram_missing_page_token_keeps_message(db, monkeypatch):
    """No parent Page token → the DM is stored (history accrues while
    credentials are pending), nothing is sent, nothing raises."""
    monkeypatch.setattr(_consumer, "async_session", _test_session_factory())
    reply = AsyncMock(return_value=REPLY)
    monkeypatch.setattr(_consumer, "_generate_reply", reply)
    await _seed_ig_stack(db, with_page_token=False)
    await _consumer._process_message(_dm_bytes())

    rows = await _messages(db)
    assert len([r for r in rows if r.direction == "inbound"]) == 1
    assert not [r for r in rows if r.direction == "outbound"]
    reply.assert_not_awaited()


@pytest.mark.asyncio
async def test_facebook_provider_messages_stay_unanswered(db, ig_mocks):
    """Messenger (object=page) is parsed + ledgered but deliberately not
    answered — its own 24h-window/handover semantics are a later phase."""
    await _seed_ig_stack(db)
    await _consumer._process_message(
        _dm_bytes(provider="facebook", asset_id=PAGE_ID, mid="pg_mid_1")
    )
    assert await _messages(db) == []
    ig_mocks.reply.assert_not_awaited()
    ig_mocks.send.assert_not_awaited()


# ── Manual sends (inbox) ride the parent Page too ─────────


@pytest.mark.asyncio
async def test_dispatch_instagram_sends_via_parent_page_token(db, monkeypatch):
    _, _, _ = await _seed_ig_stack(db)
    channel = await _seed_channel(db)
    send = AsyncMock(return_value="IgMsgProvider-9")
    monkeypatch.setattr(_ig.InstagramAdapter, "send_text_message", send)

    msg_id, error = await _channel_service._dispatch_instagram(
        db, SimpleNamespace(id=TENANT), channel, IGSID, "hello!"
    )
    assert (msg_id, error) == ("IgMsgProvider-9", "")
    send.assert_awaited_once_with(PAGE_ID, PAGE_TOKEN, IGSID, "hello!")


@pytest.mark.asyncio
async def test_dispatch_instagram_meta_failure_recorded_not_raised(db, monkeypatch):
    _, _, _ = await _seed_ig_stack(db)
    channel = await _seed_channel(db)
    monkeypatch.setattr(
        _ig.InstagramAdapter, "send_text_message",
        AsyncMock(side_effect=MetaAPIError("delivery window expired", 400)),
    )

    msg_id, error = await _channel_service._dispatch_instagram(
        db, SimpleNamespace(id=TENANT), channel, IGSID, "hello!"
    )
    assert msg_id == ""
    assert "delivery window expired" in error


@pytest.mark.asyncio
async def test_dispatch_instagram_missing_page_token_fails_with_reason(db):
    await _seed_ig_stack(db, with_page_token=False)
    channel = await _seed_channel(db)

    msg_id, error = await _channel_service._dispatch_instagram(
        db, SimpleNamespace(id=TENANT), channel, IGSID, "hello!"
    )
    assert msg_id == ""
    assert "Reconnect Instagram" in error


@pytest.mark.asyncio
async def test_dispatch_instagram_unknown_asset_fails_with_reason(db):
    channel = await _seed_channel(db, platform_user_id="ig-unknown")

    msg_id, error = await _channel_service._dispatch_instagram(
        db, SimpleNamespace(id=TENANT), channel, IGSID, "hello!"
    )
    assert msg_id == ""
    assert "No Instagram account is connected" in error


@pytest.mark.asyncio
async def test_send_message_records_failure_as_row_not_exception(db, monkeypatch):
    """The inbox endpoint must return a failed message row — never raise —
    so the user sees Meta's own error text instead of a 500."""
    _, _, _ = await _seed_ig_stack(db)
    channel = await _seed_channel(db)
    monkeypatch.setattr(
        _ig.InstagramAdapter, "send_text_message",
        AsyncMock(side_effect=MetaAPIError("no matching customer", 400)),
    )

    row = await _channel_service.send_message(
        channel.id,
        ChannelMessageSend(contact_phone=IGSID, content="hello"),
        SimpleNamespace(id=TENANT),
        db,
    )
    assert row.status == "failed"
    assert "no matching customer" in (row.error or "")


# ── Webhook subscription on asset selection ───────────────


@pytest.mark.asyncio
async def test_selecting_page_subscribes_messaging_webhooks(db, monkeypatch):
    conn = MetaConnection(
        id=str(uuid.uuid4()), tenant_id=TENANT, provider="facebook",
        access_token_encrypted="x", status="active", connection_type="oauth",
    )
    page = MetaAsset(
        id=str(uuid.uuid4()), tenant_id=TENANT, connection_id=conn.id,
        provider="facebook", asset_type="page", external_asset_id=PAGE_ID,
        asset_metadata={"page_access_token": PAGE_TOKEN},
    )
    db.add_all([conn, page])
    await db.commit()
    sub = AsyncMock()
    monkeypatch.setattr(FacebookAdapter, "subscribe_page", sub)

    await _meta_service.select_assets(db, TENANT, "facebook", [page.id])

    # subscribed_apps REPLACES the field list — messages must ship with the
    # existing feed/mention fields or the other features break.
    sub.assert_awaited_once_with(
        PAGE_ID, PAGE_TOKEN, fields=["messages", "feed", "mention"]
    )
    assert page.active is True
    channel = (await db.execute(
        select(Channel).where(Channel.platform == "facebook")
    )).scalar_one()
    assert channel.platform_user_id == PAGE_ID


@pytest.mark.asyncio
async def test_selecting_ig_account_subscribes_parent_page(db, monkeypatch):
    _, page, ig = await _seed_ig_stack(db)
    sub = AsyncMock()
    monkeypatch.setattr(FacebookAdapter, "subscribe_page", sub)

    await _meta_service.select_assets(db, TENANT, "instagram", [ig.id])

    # The IG account itself is not subscribable — its parent Page is.
    sub.assert_awaited_once_with(
        PAGE_ID, PAGE_TOKEN, fields=["messages", "feed", "mention"]
    )
    assert ig.active is True
    channel = (await db.execute(
        select(Channel).where(Channel.platform == "instagram")
    )).scalar_one()
    assert channel.platform_user_id == IG_ID


@pytest.mark.asyncio
async def test_webhook_subscription_failure_does_not_block_activation(db, monkeypatch):
    conn = MetaConnection(
        id=str(uuid.uuid4()), tenant_id=TENANT, provider="facebook",
        access_token_encrypted="x", status="active", connection_type="oauth",
    )
    page = MetaAsset(
        id=str(uuid.uuid4()), tenant_id=TENANT, connection_id=conn.id,
        provider="facebook", asset_type="page", external_asset_id=PAGE_ID,
        asset_metadata={"page_access_token": PAGE_TOKEN},
    )
    db.add_all([conn, page])
    await db.commit()
    monkeypatch.setattr(
        FacebookAdapter, "subscribe_page",
        AsyncMock(side_effect=Exception("graph down")),
    )

    # Already committed before the subscription attempt: a Graph hiccup
    # must never roll the tenant's selection back.
    activated = await _meta_service.select_assets(db, TENANT, "facebook", [page.id])
    assert [a.id for a in activated] == [page.id]
    assert page.active is True

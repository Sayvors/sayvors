"""Asset deselection: unchecking an asset removes its data from the dashboard.

select_assets is a REPLACE, not an activate-only toggle: the frontend always
sends the full checked list, so anything left out was deliberately unchecked
and must go inactive — its messaging channel marked disconnected (same
semantics as a soft disconnect, history kept) so the inbox, glance cards and
Messages chart stop listing it. The consumer keeps storing inbound messages
but never lets the AI answer from a deselected asset.
"""
import uuid
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from unittest.mock import patch

from conftest import TEST_ENGINE

from app.modules.channels.meta import consumer as _consumer
from app.modules.channels.meta import service as _service
from app.modules.channels.meta.credentials import encrypt_credential
from app.modules.channels.meta.models import MetaAsset, MetaConnection
from app.modules.channels.meta.providers import facebook as _fb
from app.modules.channels.models import Channel, ChannelMessage

pytestmark = pytest.mark.asyncio

TENANT = "desel-tenant-0000-0000-0000-000000000001"


def _test_session_factory():
    """Session factory bound to the test engine (consumer opens its own)."""
    return async_sessionmaker(TEST_ENGINE, class_=AsyncSession, expire_on_commit=False)


async def _seed_connection(db, tenant_id, provider="whatsapp"):
    conn = MetaConnection(
        id=str(uuid.uuid4()), tenant_id=tenant_id, provider=provider,
        access_token_encrypted="x", status="active", connection_type="oauth",
    )
    db.add(conn)
    await db.commit()
    await db.refresh(conn)
    return conn


async def _seed_asset(db, tenant_id, conn, external, provider=None,
                      asset_type="phone_number", **kwargs):
    asset = MetaAsset(
        id=str(uuid.uuid4()), tenant_id=tenant_id, connection_id=conn.id,
        provider=provider or conn.provider, asset_type=asset_type,
        external_asset_id=external, **kwargs,
    )
    db.add(asset)
    await db.commit()
    await db.refresh(asset)
    return asset


async def _channel_for(db, tenant_id, platform, external):
    return (
        await db.execute(
            select(Channel).where(
                Channel.user_id == tenant_id,
                Channel.platform == platform,
                Channel.platform_user_id == external,
            )
        )
    ).scalar_one_or_none()


@pytest.fixture
def no_page_webhooks(monkeypatch):
    """Page selection normally calls Graph to (re)subscribe webhooks."""
    monkeypatch.setattr(_fb.FacebookAdapter, "subscribe_page", AsyncMock(return_value=True))


async def test_deselect_hides_asset_and_disconnects_channel(db, no_page_webhooks):
    """Unchecking one of two numbers deactivates it; the kept one is intact."""
    conn = await _seed_connection(db, TENANT)
    a = await _seed_asset(db, TENANT, conn, "pn-a")
    b = await _seed_asset(db, TENANT, conn, "pn-b")

    await _service.select_assets(db, TENANT, "whatsapp", [a.id, b.id])
    await _service.select_assets(db, TENANT, "whatsapp", [a.id])

    await db.refresh(b)
    assert b.active is False
    assert b.status == "disconnected"
    await db.refresh(a)
    assert a.active is True
    chan_a = await _channel_for(db, TENANT, "whatsapp", "pn-a")
    chan_b = await _channel_for(db, TENANT, "whatsapp", "pn-b")
    assert chan_a.status == "active"
    assert chan_b.status == "disconnected"


async def test_deselect_all_clears_everything(db, no_page_webhooks):
    """An empty selection is valid: every asset of the provider goes quiet."""
    conn = await _seed_connection(db, TENANT)
    a = await _seed_asset(db, TENANT, conn, "pn-a")
    b = await _seed_asset(db, TENANT, conn, "pn-b")

    await _service.select_assets(db, TENANT, "whatsapp", [a.id, b.id])
    await _service.select_assets(db, TENANT, "whatsapp", [])

    for asset in (a, b):
        await db.refresh(asset)
        assert asset.active is False
    chan_a = await _channel_for(db, TENANT, "whatsapp", "pn-a")
    chan_b = await _channel_for(db, TENANT, "whatsapp", "pn-b")
    assert chan_a.status == "disconnected"
    assert chan_b.status == "disconnected"


async def test_reselect_restores_channel_and_history(db, no_page_webhooks):
    """Deselect → the channel hides; re-select → it and its history return."""
    conn = await _seed_connection(db, TENANT)
    asset = await _seed_asset(db, TENANT, conn, "pn-a")

    await _service.select_assets(db, TENANT, "whatsapp", [asset.id])
    chan = await _channel_for(db, TENANT, "whatsapp", "pn-a")
    db.add(ChannelMessage(
        id=str(uuid.uuid4()), channel_id=chan.id, direction="inbound",
        content="kept?", content_type="text", status="delivered",
    ))
    await db.commit()

    await _service.select_assets(db, TENANT, "whatsapp", [])
    assert (await _channel_for(db, TENANT, "whatsapp", "pn-a")).status == "disconnected"

    await _service.select_assets(db, TENANT, "whatsapp", [asset.id])
    await db.refresh(asset)
    assert asset.active is True
    assert (await _channel_for(db, TENANT, "whatsapp", "pn-a")).status == "active"
    msgs = (await db.execute(
        select(ChannelMessage).where(ChannelMessage.channel_id == chan.id)
    )).scalars().all()
    assert len(msgs) == 1


async def test_deselecting_page_cascades_to_ig_child(db, no_page_webhooks):
    """An IG account sends through its parent Page's token — deselecting the
    page must take the still-active IG child down with it."""
    conn = await _seed_connection(db, TENANT, provider="facebook")
    page = await _seed_asset(
        db, TENANT, conn, "page-1", provider="facebook", asset_type="page",
        name="Test Page",
    )
    ig = await _seed_asset(
        db, TENANT, conn, "ig-1", provider="instagram", asset_type="ig_account",
        parent_asset_id=page.id, username="myshop",
    )

    await _service.select_assets(db, TENANT, "facebook", [page.id])
    await _service.select_assets(db, TENANT, "instagram", [ig.id])

    # Deselect the page (facebook tab) — the instagram tab was not touched.
    await _service.select_assets(db, TENANT, "facebook", [])

    await db.refresh(page)
    await db.refresh(ig)
    assert page.active is False
    assert ig.active is False
    assert ig.status == "disconnected"
    ig_chan = await _channel_for(db, TENANT, "instagram", "ig-1")
    assert ig_chan.status == "disconnected"


async def test_selection_leaves_other_provider_untouched(db, no_page_webhooks):
    """Deselecting everything on facebook never touches active whatsapp assets."""
    conn = await _seed_connection(db, TENANT)
    wa = await _seed_asset(db, TENANT, conn, "pn-a")
    fb_conn = await _seed_connection(db, TENANT, provider="facebook")
    page = await _seed_asset(
        db, TENANT, fb_conn, "page-1", provider="facebook", asset_type="page",
    )

    await _service.select_assets(db, TENANT, "whatsapp", [wa.id])
    await _service.select_assets(db, TENANT, "facebook", [page.id])
    await _service.select_assets(db, TENANT, "facebook", [])

    await db.refresh(wa)
    assert wa.active is True
    chan = await _channel_for(db, TENANT, "whatsapp", "pn-a")
    assert chan.status == "active"


async def test_deselected_whatsapp_asset_stores_message_without_reply(db, monkeypatch):
    """Inbound to a deselected number: kept for history, AI stays silent."""
    conn = await _seed_connection(db, TENANT)
    conn.access_token_encrypted = encrypt_credential("tok")
    await db.commit()
    asset = await _seed_asset(db, TENANT, conn, "pn-a")
    await _service.select_assets(db, TENANT, "whatsapp", [asset.id])
    await _service.select_assets(db, TENANT, "whatsapp", [])  # deselected

    monkeypatch.setattr(_consumer, "async_session", _test_session_factory())
    m_reply = AsyncMock(return_value="should not be generated")
    m_adapter = AsyncMock()
    monkeypatch.setattr(_consumer, "_generate_reply", m_reply)
    monkeypatch.setattr(_service, "get_adapter", lambda _p: m_adapter)

    await _consumer._handle_message_received(
        {"external_asset_id": "pn-a", "external_event_id": "wamid-1"},
        {"from": "+15550001", "text": "hello", "msg_type": "text"},
    )

    m_reply.assert_not_awaited()
    m_adapter.send_text_message.assert_not_awaited()
    chan = await _channel_for(db, TENANT, "whatsapp", "pn-a")
    msgs = (await db.execute(
        select(ChannelMessage).where(ChannelMessage.channel_id == chan.id)
    )).scalars().all()
    assert [m.content for m in msgs] == ["hello"]


async def test_deselected_ig_asset_stores_message_without_reply(db, monkeypatch):
    """Same rule on Instagram — including the page-deselection cascade."""
    conn = await _seed_connection(db, TENANT, provider="facebook")
    page = await _seed_asset(
        db, TENANT, conn, "page-1", provider="facebook", asset_type="page",
        name="Test Page", active=True,
        asset_metadata={"page_access_token": "page-token"},
    )
    ig = await _seed_asset(
        db, TENANT, conn, "ig-1", provider="instagram", asset_type="ig_account",
        parent_asset_id=page.id, username="myshop",
    )
    await _service.select_assets(db, TENANT, "instagram", [ig.id])
    # The page is deselected → the IG child cascades off…
    await _service.select_assets(db, TENANT, "facebook", [])
    await db.refresh(ig)
    assert ig.active is False

    monkeypatch.setattr(_consumer, "async_session", _test_session_factory())
    m_reply = AsyncMock(return_value="should not be generated")
    m_send = AsyncMock(return_value="msg-id")
    m_typing = AsyncMock(return_value=True)
    m_profile = AsyncMock(return_value={})
    monkeypatch.setattr(_consumer, "_generate_reply", m_reply)
    from app.modules.channels.meta.providers import instagram as _ig

    monkeypatch.setattr(_ig.InstagramAdapter, "send_text_message", m_send)
    monkeypatch.setattr(_ig.InstagramAdapter, "send_typing_indicator", m_typing)
    monkeypatch.setattr(_ig.InstagramAdapter, "get_contact_profile", m_profile)

    await _consumer._handle_instagram_message(
        {"external_asset_id": "ig-1", "external_event_id": "mid-1"},
        {"field": "messages", "raw": {
            "sender": {"id": "igsid-1"},
            "recipient": {"id": "ig-1"},
            "message": {"mid": "mid-1", "text": "do you deliver?"},
        }},
    )

    m_reply.assert_not_awaited()
    m_send.assert_not_awaited()
    chan = await _channel_for(db, TENANT, "instagram", "ig-1")
    msgs = (await db.execute(
        select(ChannelMessage).where(ChannelMessage.channel_id == chan.id)
    )).scalars().all()
    assert [m.content for m in msgs] == ["do you deliver?"]

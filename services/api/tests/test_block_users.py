"""WA-6: block / unblock a customer without leaving the inbox.

WhatsApp owns the block; these tests pin the adapter payload and the mirrored
thread state the inbox reads back.
"""
import uuid

import pytest
from sqlalchemy import select

from app.modules.channels.meta.credentials import encrypt_credential
from app.modules.channels.meta.models import MetaAsset, MetaConnection
from app.modules.channels.meta.providers.whatsapp import WhatsAppAdapter
from app.modules.channels.models import Channel, ChannelThread
from app.modules.channels.service import hash_contact_phone

PHONE_ID = "pn-block-1"
CUSTOMER = "+966500008888"


async def _seed(db, user_id):
    conn = MetaConnection(
        id=str(uuid.uuid4()), tenant_id=user_id, provider="whatsapp",
        access_token_encrypted=encrypt_credential("tok"), status="active",
    )
    db.add(conn)
    await db.flush()
    db.add(MetaAsset(
        id=str(uuid.uuid4()), tenant_id=user_id, connection_id=conn.id,
        provider="whatsapp", asset_type="phone_number",
        external_asset_id=PHONE_ID, phone="+1555", active=True,
    ))
    channel = Channel(
        id=str(uuid.uuid4()), user_id=user_id, platform="whatsapp",
        platform_user_id=PHONE_ID, display_name="Blocks", status="active",
    )
    db.add(channel)
    await db.commit()
    return channel


@pytest.mark.asyncio
async def test_block_then_unblock_mirrors_the_thread_state(
    client, db, user_id, monkeypatch
):
    channel = await _seed(db, user_id)
    calls: list[tuple[str, str]] = []

    async def _block(self, phone_number_id, token, user_id_):
        calls.append(("block", user_id_))
        return {"block_users": [{"user": user_id_}]}

    async def _unblock(self, phone_number_id, token, user_id_):
        calls.append(("unblock", user_id_))
        return {"block_users": [{"user": user_id_}]}

    monkeypatch.setattr(WhatsAppAdapter, "block_user", _block)
    monkeypatch.setattr(WhatsAppAdapter, "unblock_user", _unblock)

    url = (
        f"/api/v1/inbox/threads/{channel.id}/"
        f"{CUSTOMER.replace('+', '%2B')}/block"
    )
    blocked = client.post(url)
    assert blocked.status_code == 200, blocked.text
    assert blocked.json()["blocked_at"]
    assert calls == [("block", CUSTOMER)]

    row = (
        await db.execute(
            select(ChannelThread).where(
                ChannelThread.channel_id == channel.id,
                ChannelThread.contact_phone_hash == hash_contact_phone(CUSTOMER),
            )
        )
    ).scalar_one()
    assert row.blocked_at is not None
    assert row.blocked_by == user_id

    unblocked = client.delete(url)
    assert unblocked.status_code == 200, unblocked.text
    assert unblocked.json()["blocked_at"] is None
    assert calls[-1] == ("unblock", CUSTOMER)

    await db.refresh(row)
    assert row.blocked_at is None
    assert row.blocked_by is None


@pytest.mark.asyncio
async def test_block_rejects_a_non_whatsapp_channel(
    client, db, user_id
):
    channel = Channel(
        id=f"chan-ig-block-{uuid.uuid4().hex[:8]}", user_id=user_id,
        platform="instagram", platform_user_id="ig-block",
        display_name="IG", status="active",
    )
    db.add(channel)
    await db.commit()

    url = (
        f"/api/v1/inbox/threads/{channel.id}/"
        f"{CUSTOMER.replace('+', '%2B')}/block"
    )
    res = client.post(url)
    assert res.status_code == 422, res.text


@pytest.mark.asyncio
async def test_block_requires_a_channel_owned_by_the_tenant(
    client, db, other_user_id
):
    channel = await _seed(db, other_user_id)
    url = (
        f"/api/v1/inbox/threads/{channel.id}/"
        f"{CUSTOMER.replace('+', '%2B')}/block"
    )
    assert client.post(url).status_code == 404

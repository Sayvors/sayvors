"""Disconnect semantics: soft disconnect keeps history; delete_data purges it.

The UI offers both — "disconnect only" (reconnect and everything is still
there) and "disconnect & delete everything" (reconnect and start from
scratch). The purge must take the channels' messages down first
(channel_messages has no DB cascade) and remove every connection row.

One connection per (tenant, provider) is a DB constraint: the dev seed's
connection was replaced in place by the real signup, which is why its
leftover assets carry {"source": "dev_seed"} on the asset row itself.
"""
import uuid

import pytest
from sqlalchemy import select

from app.modules.channels.meta import service as _service
from app.modules.channels.meta.models import MetaAsset, MetaConnection
from app.modules.channels.models import Channel, ChannelMessage

pytestmark = pytest.mark.asyncio

TENANT = "purge-tenant-0000-0000-0000-000000000001"
OTHER = "purge-other-0000-0000-0000-000000000002"


async def _seed_connection(db, tenant_id, connection_type="oauth"):
    conn = MetaConnection(
        id=str(uuid.uuid4()), tenant_id=tenant_id, provider="whatsapp",
        access_token_encrypted="x", status="active",
        connection_type=connection_type,
    )
    db.add(conn)
    await db.commit()
    await db.refresh(conn)
    return conn


async def _seed_asset(db, tenant_id, conn, external, dev_seed=False):
    asset = MetaAsset(
        id=str(uuid.uuid4()), tenant_id=tenant_id, connection_id=conn.id,
        provider="whatsapp", asset_type="phone_number",
        external_asset_id=external, name="Test Number",
        asset_metadata={"source": "dev_seed"} if dev_seed else {},
    )
    db.add(asset)
    await db.commit()
    return asset


async def _seed_channel_with_messages(db, tenant_id, n=2):
    channel = Channel(
        id=str(uuid.uuid4()), user_id=tenant_id, platform="whatsapp",
        platform_user_id="pn-1",
    )
    db.add(channel)
    for i in range(n):
        db.add(ChannelMessage(
            id=str(uuid.uuid4()), channel_id=channel.id,
            direction="inbound", content=f"msg-{i}",
            content_type="text", status="delivered",
        ))
    await db.commit()
    return channel


async def _counts(db, tenant_id):
    conns = len((await db.execute(
        select(MetaConnection).where(MetaConnection.tenant_id == tenant_id)
    )).scalars().all())
    assets = len((await db.execute(
        select(MetaAsset).where(MetaAsset.tenant_id == tenant_id)
    )).scalars().all())
    channels = len((await db.execute(
        select(Channel).where(Channel.user_id == tenant_id)
    )).scalars().all())
    return conns, assets, channels


async def test_soft_disconnect_keeps_history(db):
    conn = await _seed_connection(db, TENANT)
    asset = await _seed_asset(db, TENANT, conn, "pn-1")
    channel = await _seed_channel_with_messages(db, TENANT)

    await _service.disconnect(db, TENANT, "whatsapp")

    assert (await db.get(MetaConnection, conn.id)).status == "revoked"
    assert (await db.get(MetaAsset, asset.id)).active is False
    # The channel itself is marked disconnected — the inbox stops listing it —
    # but the row and its messages survive for the reconnect.
    assert (await db.get(Channel, channel.id)).status == "disconnected"
    conns, assets, channels = await _counts(db, TENANT)
    assert (conns, assets, channels) == (1, 1, 1)
    msgs = (await db.execute(
        select(ChannelMessage).where(ChannelMessage.channel_id == channel.id)
    )).scalars().all()
    assert len(msgs) == 2


async def test_reconnect_same_number_reactivates_channel(db):
    """Disconnect hides the number from the inbox; selecting the same number
    again after a reconnect brings the channel and its history back."""
    conn = await _seed_connection(db, TENANT)
    asset = await _seed_asset(db, TENANT, conn, "pn-1")
    channel = await _seed_channel_with_messages(db, TENANT)

    await _service.disconnect(db, TENANT, "whatsapp")
    assert (await db.get(Channel, channel.id)).status == "disconnected"

    activated = await _service.select_assets(db, TENANT, "whatsapp", [asset.id])

    assert asset.id in [a.id for a in activated]
    assert (await db.get(Channel, channel.id)).status == "active"
    msgs = (await db.execute(
        select(ChannelMessage).where(ChannelMessage.channel_id == channel.id)
    )).scalars().all()
    assert len(msgs) == 2


async def test_disconnect_without_connection_row_still_disconnects(db):
    """A missing connection row must not turn the endpoint into a silent
    no-op: the channel it served still gets marked disconnected (its assets
    cascade away with the connection row itself)."""
    conn = await _seed_connection(db, TENANT)
    channel = await _seed_channel_with_messages(db, TENANT)

    await db.delete(conn)
    await db.commit()

    result = await _service.disconnect(db, TENANT, "whatsapp")

    assert result == {"deleted": {}}
    assert (await db.get(Channel, channel.id)).status == "disconnected"
    msgs = (await db.execute(
        select(ChannelMessage).where(ChannelMessage.channel_id == channel.id)
    )).scalars().all()
    assert len(msgs) == 2


async def test_disconnect_with_delete_data_purges_everything(db):
    await _seed_channel_with_messages(db, TENANT)
    conn = await _seed_connection(db, TENANT)
    await _seed_asset(db, TENANT, conn, "pn-real")
    await _seed_asset(db, TENANT, conn, "pn-dev", dev_seed=True)

    # Another tenant's whatsapp data must survive untouched.
    other_conn = await _seed_connection(db, OTHER)
    db.add(Channel(
        id=str(uuid.uuid4()), user_id=OTHER, platform="whatsapp",
        platform_user_id="pn-other",
    ))
    await db.commit()

    result = await _service.disconnect(db, TENANT, "whatsapp", delete_data=True)

    assert result["deleted"]["channels"] == 1
    assert result["deleted"]["messages"] == 2
    assert result["deleted"]["assets"] == 2
    assert result["deleted"]["connections"] == 1
    assert await _counts(db, TENANT) == (0, 0, 0)
    remaining_msgs = (await db.execute(select(ChannelMessage))).scalars().all()
    assert all(m.content != "msg-0" and m.content != "msg-1" for m in remaining_msgs)
    # Other tenant untouched.
    assert (await db.get(MetaConnection, other_conn.id)) is not None
    assert await _counts(db, OTHER) == (1, 0, 1)


async def test_list_assets_hides_dev_seed_assets(db):
    conn = await _seed_connection(db, TENANT)
    await _seed_asset(db, TENANT, conn, "pn-real")
    await _seed_asset(db, TENANT, conn, "pn-dev", dev_seed=True)

    visible = await _service.list_assets(db, TENANT, "whatsapp")
    assert [a.external_asset_id for a in visible] == ["pn-real"]

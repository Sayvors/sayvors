"""Stranded AI replies: recovery from dead outbox events.

A reply event that exhausts its retry budget stops being delivered, leaving the
inbound row pending forever. The sweep must re-drive from the dead event's own
payload (not a reconstruction), retire the old event so it is not retried
forever, cap re-drives, and flag exhausted rows instead of silently rotting.
"""
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.channels import reply_recovery
from app.modules.channels.models import ChannelMessage
from app.modules.outbox.models import EventOutbox

pytestmark = pytest.mark.asyncio

WAMID = "wamid-stranded-0001"


@pytest_asyncio.fixture
async def recovery_db(db, monkeypatch):
    factory = async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(reply_recovery, "async_session", factory)
    return db


def _envelope(tenant_id="tenant-recovery-1"):
    return {
        "provider": "whatsapp",
        "event_type": "message.received",
        "external_event_id": WAMID,
        "external_asset_id": "asset-1",
        "tenant_id": tenant_id,
        "payload": {"from": "+15550000001", "text": "hello", "msg_type": "text"},
    }


async def _dead_event(db, *, status="dead", attempts=8):
    row = EventOutbox(
        id="event-dead-1", event_type="meta.message.received",
        payload=_envelope(), topic="meta-events", status=status,
        attempts=attempts,
        created_at=datetime.now(timezone.utc) - timedelta(hours=2),
    )
    db.add(row)
    await db.commit()
    return row


async def _inbound(db, channel_id, *, ai_status="pending", attempts=0):
    row = ChannelMessage(
        id="msg-stranded-1", channel_id=channel_id,
        platform_message_id=WAMID, direction="inbound",
        content="encrypted", content_type="text", status="delivered",
        ai_reply_status=ai_status, ai_reply_attempts=attempts,
        created_at=datetime.now(timezone.utc) - timedelta(hours=2),
    )
    db.add(row)
    await db.commit()
    return row


async def _events(db):
    return (await db.execute(select(EventOutbox))).scalars().all()


async def test_dead_event_with_pending_reply_is_redriven(recovery_db, channel_id):
    dead = await _dead_event(recovery_db)
    inbound = await _inbound(recovery_db, channel_id)

    stats = await reply_recovery.recover_stranded_replies()
    await recovery_db.refresh(inbound)
    await recovery_db.refresh(dead)
    assert stats["redriven"] == 1
    assert inbound.ai_reply_attempts == 1
    assert (await recovery_db.get(EventOutbox, dead.id)).status == "recovered"
    fresh = [e for e in await _events(recovery_db) if e.id != dead.id]
    assert len(fresh) == 1
    assert fresh[0].status == "pending"
    assert fresh[0].payload == dead.payload
    assert fresh[0].event_type == "meta.message.received"


async def test_second_run_does_not_redrive_the_same_event(recovery_db, channel_id):
    await _dead_event(recovery_db)
    await _inbound(recovery_db, channel_id)
    await reply_recovery.recover_stranded_replies()

    stats = await reply_recovery.recover_stranded_replies()

    assert stats["redriven"] == 0
    assert stats["scanned"] == 0


async def test_exhausted_reply_is_flagged_not_redriven(recovery_db, channel_id):
    dead = await _dead_event(recovery_db)
    inbound = await _inbound(
        recovery_db, channel_id,
        attempts=reply_recovery.MAX_RECOVERY_ATTEMPTS,
    )

    stats = await reply_recovery.recover_stranded_replies()

    assert stats["flagged"] == 1 and stats["redriven"] == 0
    await recovery_db.refresh(inbound)
    assert inbound.ai_reply_status == "failed"
    assert "exhausted" in inbound.ai_reply_error
    await recovery_db.refresh(dead)
    assert dead.status == "recovered"


async def test_terminal_row_retires_the_dead_event(recovery_db, channel_id):
    dead = await _dead_event(recovery_db)
    await _inbound(recovery_db, channel_id, ai_status="sent")

    stats = await reply_recovery.recover_stranded_replies()

    assert stats["settled"] == 1 and stats["redriven"] == 0
    await recovery_db.refresh(dead)
    assert dead.status == "recovered"
    assert len(await _events(recovery_db)) == 1

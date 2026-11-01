"""The raw Meta webhook ledger must actually be swept.

The worker writes a terminal status when it finishes an event, so the normal
path is bounded. A row that never reaches a terminal status is an orphan (an
unknown asset, or an outbox event that died before the worker could close it);
those get a shorter window so a bug in the pipeline cannot turn the ledger
into an unbounded table again.
"""
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.channels.meta.models import MetaWebhookEvent
from app.modules.retention import (
    WEBHOOK_EVENT_ORPHAN_RETENTION_DAYS,
    WEBHOOK_EVENT_RETENTION_DAYS,
    cleanup_webhook_events,
)


@pytest_asyncio.fixture
async def retention_db(db, monkeypatch):
    """Point the sweep at the test database."""
    factory = async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("app.modules.retention.async_session", factory)
    yield db


def _event(event_id: str, status: str, age_days: float) -> MetaWebhookEvent:
    return MetaWebhookEvent(
        id=event_id,
        provider="whatsapp",
        external_event_id=f"wamid.{event_id}",
        event_type="message.status",
        raw_payload={"status": status},
        status=status,
        created_at=datetime.now(timezone.utc) - timedelta(days=age_days),
    )


async def _ids(db) -> set[str]:
    rows = (await db.execute(select(MetaWebhookEvent))).scalars().all()
    return {str(row.id) for row in rows}


@pytest.mark.asyncio
async def test_terminal_rows_expire_and_live_ones_survive(retention_db):
    db = retention_db
    db.add_all([
        _event("wh-processed-old", "processed", WEBHOOK_EVENT_RETENTION_DAYS + 5),
        _event("wh-duplicate-old", "duplicate", WEBHOOK_EVENT_RETENTION_DAYS + 5),
        _event("wh-rejected-old", "rejected", WEBHOOK_EVENT_RETENTION_DAYS + 5),
        _event("wh-processed-new", "processed", 10),
        _event("wh-received-fresh", "received", 2),
        _event("wh-unresolved-fresh", "unresolved", 2),
    ])
    await db.commit()

    deleted = await cleanup_webhook_events()

    assert deleted == 3
    assert await _ids(db) == {
        "wh-processed-new",
        "wh-received-fresh",
        "wh-unresolved-fresh",
    }


@pytest.mark.asyncio
async def test_orphans_expire_sooner_than_terminal_rows(retention_db):
    db = retention_db
    db.add_all([
        # Past the orphan window, well inside the terminal window.
        _event("wh-received-orphan", "received",
               WEBHOOK_EVENT_ORPHAN_RETENTION_DAYS + 2),
        _event("wh-unresolved-orphan", "unresolved",
               WEBHOOK_EVENT_ORPHAN_RETENTION_DAYS + 2),
        # A terminal row of the same age is still history worth keeping.
        _event("wh-processed-same-age", "processed",
               WEBHOOK_EVENT_ORPHAN_RETENTION_DAYS + 2),
    ])
    await db.commit()

    deleted = await cleanup_webhook_events()

    assert deleted == 2
    assert await _ids(db) == {"wh-processed-same-age"}

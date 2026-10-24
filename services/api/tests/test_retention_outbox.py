"""The outbox dispatch log must not grow forever.

Sent rows are dispatch history and go after a day. Dead rows exhausted their
retries; they are kept a month so an operator can still inspect the failure,
then removed. Pending and failed rows are still deliverable work and must
never be swept.

The sweep is batched: one unbounded DELETE on a large outbox holds locks for
the whole statement. These tests pin both the status filter and the bound.
"""
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.outbox.models import EventOutbox
from app.modules.outbox import service as outbox_service


@pytest_asyncio.fixture
async def outbox_db(db, monkeypatch):
    """Point the sweep at the test database."""
    factory = async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(outbox_service, "async_session", factory)
    yield db


def _event(event_id: str, status: str, age_days: float = 0) -> EventOutbox:
    created = datetime.now(timezone.utc) - timedelta(days=age_days)
    return EventOutbox(
        id=event_id,
        event_type="auth.password_reset",
        payload={},
        status=status,
        attempts=0,
        next_retry_at=created,
        topic="auth-events",
        created_at=created,
    )


async def _ids(db) -> set[str]:
    rows = (await db.execute(select(EventOutbox))).scalars().all()
    return {str(row.id) for row in rows}


@pytest.mark.asyncio
async def test_only_terminal_old_events_are_deleted(outbox_db):
    outbox_db.add_all(
        [
            _event("sent-old", "sent", age_days=2),
            _event("sent-fresh", "sent", age_days=0.1),
            _event("dead-old", "dead", age_days=40),
            _event("dead-fresh", "dead", age_days=5),
            _event("pending-old", "pending", age_days=40),
            _event("failed-old", "failed", age_days=40),
        ]
    )
    await outbox_db.commit()

    deleted = await outbox_service.cleanup_outbox_events()

    assert deleted == 2
    assert await _ids(outbox_db) == {
        "sent-fresh",
        "dead-fresh",
        "pending-old",
        "failed-old",
    }


@pytest.mark.asyncio
async def test_cleanup_walks_multiple_batches(outbox_db, monkeypatch):
    monkeypatch.setattr(outbox_service, "OUTBOX_DELETE_BATCH", 2)
    monkeypatch.setattr(outbox_service, "OUTBOX_MAX_BATCHES", 10)
    outbox_db.add_all([_event(f"sent-{i}", "sent", age_days=2) for i in range(5)])
    await outbox_db.commit()

    deleted = await outbox_service.cleanup_outbox_events()

    assert deleted == 5
    assert await _ids(outbox_db) == set()


@pytest.mark.asyncio
async def test_cleanup_is_bounded_per_run(outbox_db, monkeypatch):
    """A huge backlog is worked through over several runs, not one long
    transaction that holds locks until it finishes."""
    monkeypatch.setattr(outbox_service, "OUTBOX_DELETE_BATCH", 2)
    monkeypatch.setattr(outbox_service, "OUTBOX_MAX_BATCHES", 1)
    outbox_db.add_all([_event(f"sent-{i}", "sent", age_days=2) for i in range(5)])
    await outbox_db.commit()

    deleted = await outbox_service.cleanup_outbox_events()

    assert deleted == 2
    assert len(await _ids(outbox_db)) == 3

"""Retention for the two tables that previously grew forever.

ReviewResponseLog writes one row per LLM generation in the review pipeline;
ConnectImportEvent appends a progress line per connect-import step. Neither
had a cleanup job, so both grew for the life of the tenant. The sweeps use the
existing bounded batched delete framework and must leave recent rows alone.
"""
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.channels.models import ConnectImportEvent
from app.modules.review_engine.models import ReviewResponseLog


@pytest_asyncio.fixture
async def retention_db(db, monkeypatch):
    factory = async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("app.modules.retention.async_session", factory)
    yield db


def _age(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


async def _log(db, row_id: str, days: int) -> None:
    db.add(ReviewResponseLog(
        id=row_id, tenant_id="tenant-growth-0001", created_at=_age(days),
    ))
    await db.commit()


async def _event(db, row_id: str, days: int) -> None:
    db.add(ConnectImportEvent(
        id=row_id, session_id="session-growth-0001", message="progress",
        created_at=_age(days),
    ))
    await db.commit()


@pytest.mark.asyncio
async def test_old_review_logs_are_deleted_and_recent_kept(retention_db):
    from app.modules.retention import cleanup_review_response_logs

    await _log(retention_db, "log-old", 120)
    await _log(retention_db, "log-new", 5)
    assert await cleanup_review_response_logs() == 1
    remaining = await _ids(retention_db, ReviewResponseLog)
    assert remaining == {"log-new"}


@pytest.mark.asyncio
async def test_old_connect_events_are_deleted_and_recent_kept(retention_db):
    from app.modules.retention import cleanup_connect_import_events

    await _event(retention_db, "event-old", 60)
    await _event(retention_db, "event-new", 2)
    assert await cleanup_connect_import_events() == 1
    remaining = await _ids(retention_db, ConnectImportEvent)
    assert remaining == {"event-new"}


async def _ids(db, model) -> set[str]:
    rows = (await db.execute(select(model))).scalars().all()
    return {str(row.id) for row in rows}


@pytest.mark.asyncio
async def test_cleanup_all_registers_both_new_sweeps(monkeypatch):
    import app.modules.retention as retention

    async def _zero():
        return 0

    for name in (
        "cleanup_webhook_events", "cleanup_notifications",
        "cleanup_usage_events", "cleanup_jobs",
        "cleanup_competitor_history", "cleanup_review_response_logs",
        "cleanup_connect_import_events",
    ):
        monkeypatch.setattr(retention, name, _zero)

    counts = await retention.cleanup_all()
    assert counts["review_response_logs"] == 0
    assert counts["connect_import_events"] == 0

"""The jobs table needs a retention window.

The jobs table is the execution record: one row per AI reply, publish,
transcription and media job. Nothing deleted it, so it grew for every job
the platform ever ran — the table that eventually takes the database down.

Only terminal rows are history. A queued, running, retrying or blocked job
is live work and must never be swept.
"""
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.jobs.models import Job, JobStatus
from app.modules.retention import cleanup_jobs


@pytest_asyncio.fixture
async def retention_db(db, monkeypatch):
    """Point the sweep at the test database."""
    factory = async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("app.modules.retention.async_session", factory)
    yield db


async def _job(db, job_id: str, status: str, age_days: int) -> None:
    db.add(
        Job(
            id=job_id,
            tenant_id="tenant-retention-0001",
            job_type="meta.send_reply",
            lane="realtime",
            status=status,
            priority=50,
            payload={},
            lane_key=job_id,
            attempts=0,
            max_attempts=5,
            next_run_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc) - timedelta(days=age_days),
        )
    )
    await db.commit()


async def _ids(db) -> set[str]:
    rows = (await db.execute(select(Job))).scalars().all()
    return {str(row.id) for row in rows}


@pytest.mark.asyncio
async def test_old_terminal_jobs_are_deleted(retention_db):
    await _job(retention_db, "job-old-success", JobStatus.succeeded.value, 45)
    await _job(retention_db, "job-old-cancelled", JobStatus.cancelled.value, 45)
    await _job(retention_db, "job-old-failed", JobStatus.failed.value, 120)
    await _job(retention_db, "job-old-dead", JobStatus.dead.value, 120)
    await _job(retention_db, "job-new-success", JobStatus.succeeded.value, 2)
    await _job(retention_db, "job-fresh-failed", JobStatus.failed.value, 40)

    deleted = await cleanup_jobs()
    assert deleted == 4
    assert await _ids(retention_db) == {"job-new-success", "job-fresh-failed"}


@pytest.mark.asyncio
async def test_live_jobs_are_never_swept(retention_db):
    await _job(retention_db, "job-queued", JobStatus.queued.value, 200)
    await _job(retention_db, "job-running", JobStatus.running.value, 200)
    await _job(retention_db, "job-retrying", JobStatus.retrying.value, 200)
    await _job(retention_db, "job-blocked", JobStatus.blocked.value, 200)
    await _job(retention_db, "job-accepted", JobStatus.accepted.value, 200)

    deleted = await cleanup_jobs()
    assert deleted == 0
    assert await _ids(retention_db) == {
        "job-queued",
        "job-running",
        "job-retrying",
        "job-blocked",
        "job-accepted",
    }

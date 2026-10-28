"""Job foundations: outbox dedupe, hard deadlines, lane heartbeats.

The three Phase-0 items that were still open:

* a retried producer write used to enqueue the same event twice;
* a job scheduled far out had no deadline, so a backlog after an outage
  became a burst of late external calls;
* a lane that stopped ticking was invisible.
"""
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.jobs.models import Job, JobLaneHeartbeat, JobStatus
from app.modules.jobs.reaper import report_stuck_lanes
from app.modules.jobs.service import claim_due_jobs
from app.modules.outbox.models import EventOutbox
from app.modules.outbox.service import enqueue_event_in


@pytest_asyncio.fixture
async def jobs_factory(db, monkeypatch):
    """Point the job machinery at the test database.

    Yields a session factory: the runner writes on its own session, so a
    fresh session is the honest way to read its writes back (a stale
    identity-mapped row in the test session would hide the change).
    """
    factory = async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("app.modules.jobs.runner.async_session", factory)
    monkeypatch.setattr("app.modules.jobs.service.async_session", factory)
    return factory


@pytest.mark.asyncio
async def test_outbox_dedupe_key_writes_the_event_once(db):
    """The same key returns the first event instead of a second one."""
    first = await enqueue_event_in(
        db, "review.discovered", {"review_id": "r1"}, topic="review-events",
        dedupe_key="review:tenant-1:r1",
    )
    await db.commit()
    second = await enqueue_event_in(
        db, "review.discovered", {"review_id": "r1"}, topic="review-events",
        dedupe_key="review:tenant-1:r1",
    )
    await db.commit()

    assert second == first
    rows = (await db.execute(select(EventOutbox))).scalars().all()
    assert len(rows) == 1
    assert rows[0].dedupe_key == "review:tenant-1:r1"


@pytest.mark.asyncio
async def test_events_without_a_key_are_unaffected(db):
    """NULL keys never collide - a unique index ignores NULLs."""
    await enqueue_event_in(db, "review.discovered", {"n": 1}, topic="review-events")
    await enqueue_event_in(db, "review.discovered", {"n": 2}, topic="review-events")
    await db.commit()

    rows = (await db.execute(select(EventOutbox))).scalars().all()
    assert len(rows) == 2
    assert all(row.dedupe_key is None for row in rows)


async def _job(db, job_id: str, **kwargs) -> Job:
    now = datetime.now(timezone.utc)
    fields = {
        "id": job_id,
        "tenant_id": "tenant-jobs-0001",
        "job_type": "stt.job",
        "lane": "bulk",
        "status": JobStatus.queued.value,
        "priority": 50,
        "payload": {},
        "lane_key": job_id,
        "attempts": 0,
        "max_attempts": 5,
        "next_run_at": now,
        "created_at": now,
    }
    fields.update(kwargs)
    job = Job(**fields)
    db.add(job)
    await db.commit()
    return job


@pytest.mark.asyncio
async def test_a_job_becomes_due_at_its_deadline(db, jobs_factory):
    """The deadline clamps the schedule: due AT the deadline, not later."""
    now = datetime.now(timezone.utc)
    await _job(
        db,
        "job-deadline-due",
        next_run_at=now + timedelta(hours=5),
        hard_deadline_at=now - timedelta(minutes=1),
    )

    claimed = await claim_due_jobs(db, lane="bulk", worker_id="worker-1", limit=10)
    await db.commit()
    assert [job.id for job in claimed] == ["job-deadline-due"]


@pytest.mark.asyncio
async def test_a_job_past_its_deadline_is_cancelled_not_run(db, jobs_factory, monkeypatch):
    """Running it late is a wrong outcome, not a late one."""
    from app.modules.jobs import runner as runner_module

    called = {"handler": False}

    async def _handler(job, db):
        called["handler"] = True
        return {"ok": True}

    monkeypatch.setitem(runner_module.HANDLERS, "stt.job", _handler)

    now = datetime.now(timezone.utc)
    job = await _job(
        db,
        "job-deadline-past",
        next_run_at=now - timedelta(hours=1),
        hard_deadline_at=now - timedelta(minutes=30),
    )
    claimed = await claim_due_jobs(db, lane="bulk", worker_id="worker-1", limit=10)
    await db.commit()
    assert [j.id for j in claimed] == ["job-deadline-past"]

    runner = runner_module.JobRunner(lane="bulk", worker_id="worker-1")
    await runner._process_job(claimed[0])

    async with jobs_factory() as fresh:
        row = (await fresh.execute(select(Job).where(Job.id == job.id))).scalar_one()
        assert row.status == JobStatus.cancelled.value
        assert row.error_code == "deadline_exceeded"
    assert called["handler"] is False


@pytest.mark.asyncio
async def test_claiming_writes_a_lane_heartbeat(db, jobs_factory):
    await _job(db, "job-heartbeat")
    await claim_due_jobs(db, lane="bulk", worker_id="worker-1", limit=10)
    await db.commit()

    async with jobs_factory() as fresh:
        beat = (
            await fresh.execute(
                select(JobLaneHeartbeat).where(JobLaneHeartbeat.lane == "bulk")
            )
        ).scalar_one()
    assert beat.worker_id == "worker-1"
    assert beat.jobs_claimed == 1


@pytest.mark.asyncio
async def test_a_silent_lane_is_reported(db, jobs_factory):
    """A lane that stopped ticking must not swallow the queue unnoticed."""
    stale = datetime.now(timezone.utc) - timedelta(minutes=30)
    db.add(
        JobLaneHeartbeat(
            lane="realtime", worker_id="worker-9", last_seen_at=stale, jobs_claimed=0
        )
    )
    await db.commit()

    stuck = await report_stuck_lanes(db)
    assert "realtime" in stuck


def test_the_worker_id_names_its_replica():
    """A shared id cannot answer 'which replica holds this job?'."""
    from app.modules.jobs.runner import JobRunner

    worker_id = JobRunner(lane="realtime").worker_id
    assert worker_id.startswith("realtime-")
    assert worker_id != JobRunner(lane="realtime", worker_id="realtime-1").worker_id


async def _redis():
    from app.modules.redis.client import get_redis

    return await get_redis()


def _aware(value):
    """SQLite hands back a naive datetime for a timezone-aware column."""
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_a_tenant_at_its_cap_has_the_job_deferred(db, jobs_factory, monkeypatch):
    """At the per-tenant cap the job waits its turn instead of running."""
    from app.modules.jobs import runner as runner_module

    tenant = "tenant-cap-0001"
    key = f"job_inflight:realtime:{tenant}"
    redis = await _redis()
    await redis.set(key, runner_module.PER_TENANT_INFLIGHT_LIMIT)

    called = {"handler": False}

    async def _handler(job, db):
        called["handler"] = True
        return {"ok": True}

    monkeypatch.setitem(runner_module.HANDLERS, "stt.job", _handler)

    job = await _job(db, "job-cap-blocked", lane="realtime", tenant_id=tenant)
    claimed = await claim_due_jobs(db, lane="realtime", worker_id="worker-1", limit=10)
    await db.commit()
    assert [j.id for j in claimed] == ["job-cap-blocked"]

    runner = runner_module.JobRunner(lane="realtime", worker_id="worker-1")
    await runner._process_job(claimed[0])

    async with jobs_factory() as fresh:
        row = (
            await fresh.execute(select(Job).where(Job.id == job.id))
        ).scalar_one()
        assert row.status == JobStatus.queued.value
        assert _aware(row.next_run_at) > datetime.now(timezone.utc)
    assert called["handler"] is False
    await redis.delete(key)


@pytest.mark.asyncio
async def test_a_tenant_under_the_cap_runs_its_job(db, jobs_factory, monkeypatch):
    tenant = "tenant-cap-0002"
    key = f"job_inflight:realtime:{tenant}"
    redis = await _redis()
    await redis.delete(key)

    from app.modules.jobs import runner as runner_module

    called = {"handler": False}

    async def _handler(job, db):
        called["handler"] = True
        return {"ok": True}

    monkeypatch.setitem(runner_module.HANDLERS, "stt.job", _handler)

    job = await _job(db, "job-cap-allowed", lane="realtime", tenant_id=tenant)
    claimed = await claim_due_jobs(db, lane="realtime", worker_id="worker-1", limit=10)
    await db.commit()
    assert [j.id for j in claimed] == ["job-cap-allowed"]

    runner = runner_module.JobRunner(lane="realtime", worker_id="worker-1")
    await runner._process_job(claimed[0])

    async with jobs_factory() as fresh:
        row = (
            await fresh.execute(select(Job).where(Job.id == job.id))
        ).scalar_one()
        assert row.status == JobStatus.succeeded.value, row.last_error
    assert called["handler"] is True
    await redis.delete(key)

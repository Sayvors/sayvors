"""The job pipeline: submit → claim → run.

These tests pin the behaviour the whole publishing path depends on:

- a submitted job is CLAIMABLE (the row is durable and the runner can
  see it) — a job that is inserted but not claimable never runs
- a claim is DURABLE: once committed, the row is `running` with a lease,
  so a second worker cannot claim it
- a job scheduled for the future is not claimed until it is due
- the reaper returns a crashed worker's job to the queue, and un-strands
  a row left in `accepted`

The pipeline had no coverage at all before this file, and two of these
behaviours were broken: jobs were inserted as `accepted` (which nothing
promoted) and the runner's transactions were never committed (so the
claim evaporated the moment the session closed).
"""
from datetime import datetime, timedelta, timezone

import pytest
from conftest import TEST_SESSION
from sqlalchemy import select

from app.modules.jobs.models import Job, JobStatus
from app.modules.jobs.reaper import reap_in_session
from app.modules.jobs.service import claim_due_jobs, submit_job
from app.modules.jobs.types import JobType

TENANT = "test-tenant-jobs-0000-0000-000000001"


@pytest.fixture(autouse=True)
def _schema(engine):
    """Create the schema for every test in this module."""
    yield


async def _submit(**overrides) -> Job:
    kwargs = {
        "tenant_id": TENANT,
        "job_type": JobType.post_publish.value,
        "payload": {"media_url": "https://cdn.example/p.jpg"},
        "lane": "publishing",
    }
    kwargs.update(overrides)
    async with TEST_SESSION() as db:
        job = await submit_job(db, **kwargs)
        await db.commit()
        return job


async def _reap() -> dict:
    """Run one reaper pass on the test session."""
    async with TEST_SESSION() as db:
        return await reap_in_session(db)


async def _row(job_id: str) -> Job:
    async with TEST_SESSION() as db:
        return (
            await db.execute(select(Job).where(Job.id == job_id))
        ).scalar_one_or_none()


# ── submit ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_submitted_job_is_claimable():
    """The row must be claimable the moment it commits.

    A job inserted as `accepted` was invisible to the lane runner:
    nothing promoted it, so it sat there forever. Nothing was ever
    published through this pipeline.
    """
    job = await _submit()
    assert job.status == JobStatus.queued.value

    async with TEST_SESSION() as db:
        claimed = await claim_due_jobs(db, lane="publishing", worker_id="w1", limit=10)
        await db.commit()

    assert [c.id for c in claimed] == [job.id]


@pytest.mark.asyncio
async def test_the_idempotency_key_returns_the_same_job():
    first = await _submit(idempotency_key="tenant:fb-1:post")
    second = await _submit(idempotency_key="tenant:fb-1:post")
    assert first.id == second.id


@pytest.mark.asyncio
async def test_a_job_scheduled_for_the_future_is_not_claimed():
    """`next_run_at` is how work is scheduled — a post that must come
    down on a given date is a job the runner may only claim then."""
    job = await _submit(
        next_run_at=datetime.now(timezone.utc) + timedelta(hours=2),
    )
    async with TEST_SESSION() as db:
        claimed = await claim_due_jobs(db, lane="publishing", worker_id="w1", limit=10)
        await db.commit()
    assert job.id not in [c.id for c in claimed]

    # Once it is due, it is claimable.
    async with TEST_SESSION() as db:
        row = (await db.execute(select(Job).where(Job.id == job.id))).scalar_one()
        row.next_run_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.add(row)
        await db.commit()
    async with TEST_SESSION() as db:
        claimed = await claim_due_jobs(db, lane="publishing", worker_id="w1", limit=10)
        await db.commit()
    assert job.id in [c.id for c in claimed]


# ── claim ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_a_claim_is_durable():
    """The claim must survive the session that made it.

    Until the claim is committed the row stays claimable by another
    worker — the FOR UPDATE lock is released with the transaction — so an
    uncommitted claim is no claim at all, and the same job can be run
    twice at once.
    """
    job = await _submit()
    async with TEST_SESSION() as db:
        claimed = await claim_due_jobs(db, lane="publishing", worker_id="w1", limit=10)
        await db.commit()
    assert len(claimed) == 1

    row = await _row(job.id)
    assert row.status == JobStatus.running.value
    assert row.lease_owner == "w1"
    assert row.lease_expires_at is not None


@pytest.mark.asyncio
async def test_a_claimed_job_is_not_claimed_again():
    job = await _submit()
    async with TEST_SESSION() as db:
        await claim_due_jobs(db, lane="publishing", worker_id="w1", limit=10)
        await db.commit()
    async with TEST_SESSION() as db:
        second = await claim_due_jobs(db, lane="publishing", worker_id="w2", limit=10)
        await db.commit()
    assert job.id not in [c.id for c in second]


@pytest.mark.asyncio
async def test_claims_are_scoped_to_the_lane():
    await _submit(lane="publishing")
    async with TEST_SESSION() as db:
        claimed = await claim_due_jobs(db, lane="bulk", worker_id="w1", limit=10)
        await db.commit()
    assert claimed == []


# ── reaper ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_reaper_returns_a_crashed_job_to_the_queue():
    """A worker that dies mid-call leaves the row `running` with a lease
    that has passed. It must come back, or the job is stuck forever."""
    job = await _submit()
    async with TEST_SESSION() as db:
        await claim_due_jobs(db, lane="publishing", worker_id="dead-worker", limit=10)
        await db.commit()
    async with TEST_SESSION() as db:
        row = (await db.execute(select(Job).where(Job.id == job.id))).scalar_one()
        row.lease_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.add(row)
        await db.commit()

    totals = await _reap()
    assert totals["released"] >= 1

    row = await _row(job.id)
    assert row.status == JobStatus.queued.value
    assert row.lease_owner is None


@pytest.mark.asyncio
async def test_the_reaper_un_strands_an_accepted_job():
    """A row left in `accepted` was invisible to the runner."""
    job = await _submit()
    async with TEST_SESSION() as db:
        row = (await db.execute(select(Job).where(Job.id == job.id))).scalar_one()
        row.status = JobStatus.accepted.value
        row.created_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        db.add(row)
        await db.commit()

    await _reap()

    row = await _row(job.id)
    assert row.status == JobStatus.queued.value


@pytest.mark.asyncio
async def test_the_reaper_leaves_a_healthy_lease_alone():
    job = await _submit()
    async with TEST_SESSION() as db:
        await claim_due_jobs(db, lane="publishing", worker_id="live-worker", limit=10)
        await db.commit()

    await _reap()

    row = await _row(job.id)
    assert row.status == JobStatus.running.value
    assert row.lease_owner == "live-worker"

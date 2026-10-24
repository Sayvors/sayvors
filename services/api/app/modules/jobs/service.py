"""Unified job service — submit, claim, complete, retry, cancel.

Postgres owns execution truth. All operations are transactional.
See docs/specs/2026-10-10-unified-job-processing-design.md §C.3–C.5
"""

import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ...database import async_session
from .models import Job, JobLaneHeartbeat, JobStatus
from .types import JobLane, JobType, JOB_TYPES

logger = logging.getLogger(__name__)


async def submit_job(
    db: AsyncSession,
    *,
    tenant_id: str,
    job_type: str,
    payload: dict | None = None,
    lane: str | None = None,
    priority: int = 50,
    max_attempts: int | None = None,
    idempotency_key: str | None = None,
    subject_type: str | None = None,
    subject_id: str | None = None,
    lane_key: str | None = None,
    next_run_at: datetime | None = None,
    hard_deadline_at: datetime | None = None,
) -> Job:
    """Insert a Job(row) in status=queued. Caller commits the session.

    The row is durable AND claimable the moment it commits. The lane
    runner claims from Postgres, so a row that was inserted but not
    claimable would never run — which is exactly what the design's
    `accepted` state did: nothing promoted it, because dispatching to
    Kafka is best-effort and the runner never consumes that topic. Rows
    left in `accepted` by an older build are swept by the reconciler in
    `jobs/reaper.py`.

    ``next_run_at`` is when the runner may claim the job. Leave it unset
    for "as soon as possible"; set it in the future to schedule work
    (a post that must be taken down on a given date).
    """
    if job_type not in JOB_TYPES:
        raise ValueError(f"unknown_job_type: {job_type}. known={JOB_TYPES}")

    resolved_type = JobType(job_type)
    resolved_lane = lane or JobType.lane_for(resolved_type).value
    resolved_lane_key = lane_key or str(subject_id or uuid4())

    from .types import MAX_ATTEMPTS_BY_LANE

    if max_attempts is None:
        max_attempts = MAX_ATTEMPTS_BY_LANE.get(JobLane(resolved_lane), 5)

    # Idempotency: if a job with this key already exists for this tenant, return it.
    if idempotency_key:
        existing = await db.execute(
            select(Job).where(
                Job.tenant_id == tenant_id,
                Job.idempotency_key == idempotency_key,
            )
        )
        existing_job = existing.scalar_one_or_none()
        if existing_job:
            return existing_job

    job = Job(
        id=str(uuid4()),
        tenant_id=tenant_id,
        job_type=job_type,
        lane=resolved_lane,
        status=JobStatus.queued.value,
        priority=priority,
        payload=payload or {},
        idempotency_key=idempotency_key,
        subject_type=subject_type,
        subject_id=subject_id,
        lane_key=resolved_lane_key,
        attempts=0,
        max_attempts=max_attempts,
        next_run_at=next_run_at or datetime.now(timezone.utc),
        hard_deadline_at=hard_deadline_at,
    )
    db.add(job)
    await db.flush()
    return job


async def release_expired_leases(db: AsyncSession) -> int:
    """Return jobs whose lease expired to the queue so they can be reclaimed.

    A worker that died mid-call leaves its job in `running` with a lease
    that has passed. Without this the job is stuck forever. Reclaiming it
    is safe because every handler is idempotent by job id.
    """
    now = datetime.now(timezone.utc)
    result = await db.execute(
        update(Job)
        .where(
            Job.status == JobStatus.running.value,
            Job.lease_expires_at.is_not(None),
            Job.lease_expires_at < now,
        )
        .values(
            status=JobStatus.queued.value,
            attempts=Job.attempts + 1,
            lease_expires_at=None,
            lease_owner=None,
            next_run_at=now,
        )
    )
    return result.rowcount


async def promote_accepted_jobs(db: AsyncSession, *, older_than_seconds: int = 60) -> int:
    """Promote rows stuck in `accepted` to `queued`.

    `accepted` was the design's "row exists, dispatch not confirmed"
    state. Nothing produced it, so a row that lands there is invisible to
    the runner. Sweeping it keeps a job from being stranded by an older
    build or by a dispatch path that gave up.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=older_than_seconds)
    result = await db.execute(
        update(Job)
        .where(
            Job.status == JobStatus.accepted.value,
            Job.created_at < cutoff,
        )
        .values(status=JobStatus.queued.value)
    )
    return result.rowcount


async def claim_due_jobs(
    db: AsyncSession,
    *,
    lane: str,
    worker_id: str,
    lease_seconds: int = 300,
    limit: int = 10,
) -> list[Job]:
    """Atomically claim due jobs for a lane using FOR UPDATE SKIP LOCKED.

    Returns the claimed Job rows (status=running, lease set). The caller
    MUST commit: until it does, the claim is not durable and the row
    stays claimable by another worker, because the FOR UPDATE lock is
    released when the transaction ends. A claim that is not committed is
    a claim that did not happen.

    Expired leases are reclaimed by `release_expired_leases` in the
    reaper, not here — a reclaim that is never committed is a no-op.
    """
    now = datetime.now(timezone.utc)

    # Claim due jobs: status in (queued, retrying), and due when the schedule
    # OR the hard deadline has passed. The deadline acts as a clamp
    # (LEAST(next_run_at, hard_deadline_at)): a job scheduled far out but
    # with a nearer deadline becomes due AT the deadline, so a backlog after
    # an outage is worked through in order instead of bursting at once.
    #
    # Priority aging: effective_priority = max(1, priority - age_minutes).
    # Without aging, a steady stream of priority-0 realtime work starves
    # bulk jobs forever. Age is minutes since created_at.
    from sqlalchemy import case, func

    age_minutes = func.extract("epoch", func.now() - Job.created_at) / 60.0
    effective_priority = Job.priority - func.cast(age_minutes, Integer)
    order_expr = case((effective_priority < 1, 1), else_=effective_priority)

    result = await db.execute(
        select(Job)
        .where(
            Job.lane == lane,
            Job.status.in_([JobStatus.queued.value, JobStatus.retrying.value]),
            (Job.next_run_at <= now)
            | (
                Job.hard_deadline_at.is_not(None)
                & (Job.hard_deadline_at <= now)
            ),
        )
        .order_by(order_expr, Job.next_run_at, Job.created_at)
        .with_for_update(skip_locked=True)
        .limit(limit)
    )
    jobs = list(result.scalars().all())

    lease_expires_at = now + timedelta(seconds=lease_seconds)
    for job in jobs:
        job.status = JobStatus.running.value
        job.lease_owner = worker_id
        job.lease_expires_at = lease_expires_at
        db.add(job)

    await db.flush()
    await record_lane_heartbeat(db, lane=lane, worker_id=worker_id, claimed=len(jobs))
    return jobs


async def record_lane_heartbeat(
    db: AsyncSession, *, lane: str, worker_id: str, claimed: int = 0
) -> None:
    """Refresh this lane's heartbeat row.

    A lane that stopped ticking is invisible otherwise: the queue just stops
    moving. The reaper reads these rows to report a stuck lane.
    """
    now = datetime.now(timezone.utc)
    row = (
        await db.execute(
            select(JobLaneHeartbeat).where(JobLaneHeartbeat.lane == lane)
        )
    ).scalar_one_or_none()
    if row is None:
        db.add(
            JobLaneHeartbeat(
                lane=lane, worker_id=worker_id, last_seen_at=now, jobs_claimed=claimed
            )
        )
        return
    row.worker_id = worker_id
    row.last_seen_at = now
    row.jobs_claimed = claimed
    db.add(row)


async def complete_job(
    db: AsyncSession,
    *,
    job: Job,
    result: dict | None = None,
    external_result: dict | None = None,
) -> None:
    """Mark a job succeeded, clearing lease and external_intent."""
    job.status = JobStatus.succeeded.value
    job.lease_expires_at = None
    job.lease_owner = None
    if result is not None:
        job.result = result
    if external_result is not None:
        job.external_result = external_result
    job.external_intent = None
    job.updated_at = datetime.now(timezone.utc)
    db.add(job)


async def retry_job(
    db: AsyncSession,
    *,
    job: Job,
    error: str,
    backoff_seconds: int,
    max_attempts: int | None = None,
) -> None:
    """Move a job to retrying with backoff, or dead if attempts exhausted."""
    job.attempts += 1
    job.last_error = error[:500] if error else None
    job.external_intent = None  # clear intent on retry

    max_att = max_attempts if max_attempts is not None else job.max_attempts
    if job.attempts >= max_att:
        job.status = JobStatus.dead.value
        job.error_code = "max_attempts_exhausted"
        job.lease_expires_at = None
        job.lease_owner = None
        # Publish to dead-letter topic for operator replay
        try:
            from ..outbox.service import enqueue_event_in

            await enqueue_event_in(
                db,
                "job.dead",
                {
                    "job_id": job.id,
                    "job_type": job.job_type,
                    "lane": job.lane,
                    "tenant_id": job.tenant_id,
                    "attempts": job.attempts,
                    "last_error": (job.last_error or "")[:500],
                },
                topic=f"{job.lane}-dispatch-dlq",
            )
        except Exception:
            pass  # DLQ publish is best-effort; the dead row is the truth
    else:
        job.status = JobStatus.retrying.value
        job.next_run_at = datetime.now(timezone.utc) + timedelta(seconds=backoff_seconds)
        job.lease_expires_at = None
        job.lease_owner = None

    job.updated_at = datetime.now(timezone.utc)
    db.add(job)


async def fail_job(
    db: AsyncSession,
    *,
    job: Job,
    error_code: str,
    error: str,
) -> None:
    """Terminal failure — operator retry only."""
    job.status = JobStatus.failed.value
    job.error_code = error_code
    job.last_error = error[:500] if error else None
    job.external_intent = None
    job.lease_expires_at = None
    job.lease_owner = None
    job.updated_at = datetime.now(timezone.utc)
    db.add(job)


async def cancel_job(
    db: AsyncSession,
    *,
    job: Job,
) -> bool:
    """Cancel a job if it is in a cancellable state. Returns True if cancelled."""
    cancellable = {
        JobStatus.accepted.value,
        JobStatus.queued.value,
        JobStatus.retrying.value,
        JobStatus.blocked.value,
    }
    if job.status not in cancellable:
        return False
    job.status = JobStatus.cancelled.value
    job.lease_expires_at = None
    job.lease_owner = None
    job.updated_at = datetime.now(timezone.utc)
    db.add(job)
    return True


async def block_job(
    db: AsyncSession,
    *,
    job: Job,
    release_at: datetime,
) -> None:
    """Move a job to blocked (rate limit / quota) until release_at."""
    job.status = JobStatus.blocked.value
    job.next_run_at = release_at
    job.lease_expires_at = None
    job.lease_owner = None
    job.updated_at = datetime.now(timezone.utc)
    db.add(job)


async def replay_job(db: AsyncSession, *, job_id: str, tenant_id: str) -> Job | None:
    job = await get_job(db, job_id, tenant_id)
    if job is None:
        return None
    if job.status not in (JobStatus.dead.value, JobStatus.failed.value):
        return None
    job.status = JobStatus.queued.value
    job.attempts = 0
    job.last_error = None
    job.error_code = None
    job.external_intent = None
    job.external_result = None
    job.lease_expires_at = None
    job.lease_owner = None
    job.next_run_at = datetime.now(timezone.utc)
    job.updated_at = datetime.now(timezone.utc)
    db.add(job)
    return job

async def get_job(db: AsyncSession, job_id: str, tenant_id: str) -> Job | None:
    """Fetch a job by id, tenant-scoped. Returns None if not found or wrong tenant."""
    result = await db.execute(
        select(Job).where(Job.id == job_id, Job.tenant_id == tenant_id)
    )
    return result.scalar_one_or_none()


async def list_jobs(
    db: AsyncSession,
    *,
    tenant_id: str,
    status: str | None = None,
    lane: str | None = None,
    limit: int = 50,
    cursor: str | None = None,
) -> list[Job]:
    """List jobs for a tenant with keyset pagination on (created_at, id)."""
    stmt = select(Job).where(Job.tenant_id == tenant_id)
    if status:
        stmt = stmt.where(Job.status == status)
    if lane:
        stmt = stmt.where(Job.lane == lane)
    stmt = stmt.order_by(Job.created_at.desc(), Job.id.desc()).limit(limit)
    result = await db.execute(stmt)
    return list(result.scalars().all())

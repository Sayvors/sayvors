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
from .models import Job, JobStatus
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
    max_attempts: int = 5,
    idempotency_key: str | None = None,
    subject_type: str | None = None,
    subject_id: str | None = None,
    lane_key: str | None = None,
) -> Job:
    """Insert a Job(row) in status=accepted. Caller commits the session."""
    if job_type not in JOB_TYPES:
        raise ValueError(f"unknown_job_type: {job_type}. known={JOB_TYPES}")

    resolved_lane = lane or JobType(job_type).lane_for().value
    resolved_lane_key = lane_key or str(subject_id or uuid4())

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
        status=JobStatus.accepted.value,
        priority=priority,
        payload=payload or {},
        idempotency_key=idempotency_key,
        subject_type=subject_type,
        subject_id=subject_id,
        lane_key=resolved_lane_key,
        attempts=0,
        max_attempts=max_attempts,
        next_run_at=datetime.now(timezone.utc),
    )
    db.add(job)
    await db.flush()
    return job


async def claim_due_jobs(
    db: AsyncSession,
    *,
    lane: str,
    worker_id: str,
    lease_seconds: int = 300,
    limit: int = 10,
) -> list[Job]:
    """Atomically claim due jobs for a lane using FOR UPDATE SKIP LOCKED.

    Expired leases are released first so crashed workers' jobs are reclaimable.
    Returns the claimed Job rows (status=running, lease set).
    """
    now = datetime.now(timezone.utc)

    # Release expired leases back to queued/retrying so they can be reclaimed.
    await db.execute(
        update(Job)
        .where(
            Job.lane == lane,
            Job.status == JobStatus.running.value,
            Job.lease_expires_at < now,
        )
        .values(
            status=JobStatus.queued.value,
            lease_expires_at=None,
            lease_owner=None,
        )
    )

    # Claim due jobs: status in (queued, retrying), next_run_at <= now.
    result = await db.execute(
        select(Job)
        .where(
            Job.lane == lane,
            Job.status.in_([JobStatus.queued.value, JobStatus.retrying.value]),
            Job.next_run_at <= now,
        )
        .order_by(Job.priority, Job.next_run_at, Job.created_at)
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
    return jobs


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

"""Unified job runner — lane consumer loop.

Claims jobs from Postgres (FOR UPDATE SKIP LOCKED), runs the handler,
records outcome, then commits the Kafka offset. One runner per lane.
See docs/specs/2026-10-10-unified-job-processing-design.md §C.4 / §D.5
"""

import asyncio
import json
import logging
import os
import socket
from datetime import datetime, timedelta, timezone

from ..kafka.client import create_consumer, get_kafka_producer, mark_kafka_unavailable
from ..outbox.service import enqueue_event_in
from .handlers import HANDLERS
from .models import Job, JobStatus
from .service import block_job, cancel_job, complete_job, claim_due_jobs, fail_job, retry_job
from ...database import async_session
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Per-lane concurrency cap so one lane can't starve others.
LANE_CONCURRENCY: dict[str, int] = {
    "realtime": 8,
    "publishing": 4,
    "media": 2,
    "bulk": 1,
}

# How long a claimed job's lease holds before the reaper can reclaim it.
LEASE_SECONDS = 300

# How many jobs of one tenant may run at the same time in one lane.
#
# The lane cap below is per process, so it grows with the fleet - which also
# means one noisy tenant could occupy every slot in every replica and
# starve the other tenants. Two keeps a merchant's own replies flowing
# (one running, one queued) while guaranteeing that at least half of a
# realtime lane belongs to other merchants. Set to 0 to disable.
PER_TENANT_INFLIGHT_LIMIT = 2

# How long a job waits when its tenant is at the cap. The job is durable, so
# a short wait costs the merchant nothing; dropping it would.
PER_TENANT_DEFER_SECONDS = 2.0

# TTL on the in-flight counter, so a replica that dies mid-job cannot hold
# a tenant's slot forever.
INFLIGHT_KEY_TTL_SECONDS = 300

# Poll interval when no work is available (seconds).
IDLE_POLL_SECONDS = 2


class JobRunner:
    """Single-lane job consumer loop.

    Run one instance per lane per worker replica. Multiple replicas safe:
    claims use FOR UPDATE SKIP LOCKED, leases expire and are reclaimed.
    """

    def __init__(self, lane: str, worker_id: str | None = None):
        self.lane = lane
        # Unique per replica: the heartbeat and the lease owner then name
        # the machine that actually holds a job. A shared id ("realtime-1")
        # cannot answer "which replica is stuck?".
        self.worker_id = worker_id or f"{lane}-{socket.gethostname()}-{os.getpid()}"
        self._running = False
        self._task: asyncio.Task | None = None
        self._consumer = None
        self._producer = None
        self._semaphore: asyncio.Semaphore | None = None

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._semaphore = asyncio.Semaphore(LANE_CONCURRENCY.get(self.lane, 4))

        # Provision topics + get producer (degrades gracefully if Kafka down).
        try:
            from ..kafka.topics import provision_topics
            await provision_topics()
        except Exception:
            logger.exception("Topic provisioning failed for lane %s", self.lane)

        try:
            self._producer = await get_kafka_producer()
        except Exception:
            logger.warning("Kafka unavailable for lane %s — running without dispatch", self.lane)
            mark_kafka_unavailable(f"sayvors-jobs-{self.lane}")

        topic = f"{self.lane}-dispatch"
        try:
            self._consumer = await create_consumer(
                group_id=f"sayvors-jobs-{self.lane}",
                topics=[topic],
            )
            logger.info("Job runner started: lane=%s worker=%s topic=%s", self.lane, self.worker_id, topic)
        except Exception:
            logger.exception("Failed to create Kafka consumer for lane %s", self.lane)
            self._consumer = None

        self._task = asyncio.create_task(self._loop(), name=f"job-runner-{self.lane}")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._consumer:
            try:
                await self._consumer.stop()
            except Exception:
                pass
        logger.info("Job runner stopped: lane=%s", self.lane)

    async def _loop(self) -> None:
        while self._running:
            try:
                await self._tick()
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Job runner tick error: lane=%s", self.lane)
            await asyncio.sleep(IDLE_POLL_SECONDS)

    async def _tick(self) -> None:
        # Claim due jobs from Postgres.
        async with async_session() as db:
            jobs = await claim_due_jobs(
                db,
                lane=self.lane,
                worker_id=self.worker_id,
                limit=LANE_CONCURRENCY.get(self.lane, 4),
            )
            # The claim MUST be committed. Until it is, the row is still
            # claimable by another worker — the FOR UPDATE lock is
            # released with the transaction, so an uncommitted claim is
            # no claim at all.
            await db.commit()

        if not jobs:
            return

        # Run each claimed job concurrently (bounded by semaphore).
        async def _run_one(job: Job) -> None:
            async with self._semaphore:
                await self._process_job(job)

        await asyncio.gather(*[_run_one(j) for j in jobs], return_exceptions=True)

    async def _process_job(self, job: Job) -> None:
        """Process a single job end-to-end with idempotency + external intent."""
        handler = HANDLERS.get(job.job_type)
        if not handler:
            async with async_session() as db:
                db_job = await self._get_job_for_update(db, job.id, job.tenant_id)
                if db_job:
                    await fail_job(db, job=db_job, error_code="no_handler", error=f"no handler for {job.job_type}")
                    await db.commit()
                return

        # Provider rate-limit pacer: if the provider is cooled down, move
        # the job to blocked instead of burning an attempt.
        _PROVIDER_MAP = {
            "post.publish": "localith",
            "post.delete": "localith",
            "media.publish": "localith",
            "meta.send_reply": "meta",
            "meta.send_template": "meta",
        }
        provider = _PROVIDER_MAP.get(job.job_type)
        if provider:
            from .pacer import is_cooled_down

            cooldown = await is_cooled_down(provider)
            if cooldown > 0:
                async with async_session() as db:
                    db_job = await self._get_job_for_update(db, job.id, job.tenant_id)
                    if db_job:
                        await block_job(db, job=db_job, release_at=datetime.now(timezone.utc) + timedelta(seconds=cooldown))
                        await db.commit()
                logger.info("Job %s blocked: provider %s cooled down for %ds", job.id, provider, cooldown)
                return

        # 1. Write the external intent durably BEFORE the external call.
        #    This is the crash-recovery record: if the worker dies
        #    mid-call, the intent is on disk and the lease expires, so
        #    the reaper returns the job to the queue.
        async with async_session() as db:
            db_job = await self._get_job_for_update(db, job.id, job.tenant_id)
            if not db_job:
                return  # claimed by another worker or cancelled

            # Idempotency: if already terminal, skip.
            if db_job.status in (JobStatus.succeeded.value, JobStatus.failed.value, JobStatus.dead.value, JobStatus.cancelled.value):
                return

            # A job past its hard deadline must not run. Running it late is
            # a wrong outcome, not a late one: a scheduled removal that runs
            # a day late leaves a post up for a day.
            deadline = db_job.hard_deadline_at
            if deadline is not None:
                # SQLite hands back a naive datetime for a timezone-aware
                # column; comparing it with an aware now() would raise.
                if deadline.tzinfo is None:
                    deadline = deadline.replace(tzinfo=timezone.utc)
                if datetime.now(timezone.utc) > deadline:
                    db_job.status = JobStatus.cancelled.value
                    db_job.error_code = "deadline_exceeded"
                    db_job.lease_expires_at = None
                    db_job.lease_owner = None
                    db.add(db_job)
                    await db.commit()
                    logger.info(
                        "Job %s cancelled: hard deadline %s has passed",
                        db_job.id,
                        db_job.hard_deadline_at,
                    )
                    return

            external_intent = {
                "job_type": db_job.job_type,
                "lane": db_job.lane,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "attempt": db_job.attempts + 1,
            }
            db_job.external_intent = external_intent
            db_job.status = JobStatus.running.value
            db_job.lease_owner = self.worker_id
            db_job.lease_expires_at = datetime.now(timezone.utc) + timedelta(
                seconds=LEASE_SECONDS
            )
            await db.commit()

        # 2. Run the handler in its own session so a slow external call
        #    does not hold a transaction (and a connection) open.
        admitted = False
        try:
            if not await self._admit_tenant(db_job.tenant_id):
                # The tenant is already at its in-flight cap. Defer the job
                # instead of running it: the work is durable, so a two second
                # wait costs the merchant nothing and dropping it would.
                await self._defer(job)
                return
            admitted = True
            async with async_session() as db:
                fresh = await self._get_job_for_update(db, job.id, job.tenant_id)
                if not fresh:
                    return
                result = await handler(fresh, db)
                # The handler's own writes (including the result it
                # records) are committed with the outcome below.
                await self._complete_in(db, fresh, result)
        except Exception as e:
            await self._fail(job, e)
        finally:
            if admitted:
                await self._release_tenant(job.tenant_id)

    async def _admit_tenant(self, tenant_id: str) -> bool:
        """Check the per-tenant in-flight cap.

        The lane cap is per process, so it scales with the fleet — which also
        means one tenant with a burst could take every slot in every replica
        and starve everyone else. This cap is the fairness guarantee: a
        tenant may have at most PER_TENANT_INFLIGHT_LIMIT jobs running in a
        lane at once.

        Redis down means fail open: the jobs table is the truth, and this is
        a guard against one noisy tenant, not a correctness gate.
        """
        if PER_TENANT_INFLIGHT_LIMIT <= 0:
            return True
        try:
            from ..redis.client import get_redis

            redis = await get_redis()
            key = f"job_inflight:{self.lane}:{tenant_id}"
            count = await redis.incr(key)
            if count == 1:
                await redis.expire(key, INFLIGHT_KEY_TTL_SECONDS)
            if count > PER_TENANT_INFLIGHT_LIMIT:
                await redis.decr(key)
                return False
            return True
        except Exception as e:
            logger.warning("Tenant admission check failed (failing open): %s", e)
            return True

    async def _release_tenant(self, tenant_id: str) -> None:
        """Give the tenant's slot back."""
        try:
            from ..redis.client import get_redis

            redis = await get_redis()
            key = f"job_inflight:{self.lane}:{tenant_id}"
            count = await redis.decr(key)
            if count <= 0:
                # Never leave a negative counter behind: it would let the
                # tenant exceed the cap until the key expired.
                await redis.delete(key)
        except Exception as e:
            logger.warning("Tenant admission release failed: %s", e)

    async def _defer(self, job: Job) -> None:
        """Put the job back on the queue, a couple of seconds out."""
        async with async_session() as db:
            fresh = await self._get_job_for_update(db, job.id, job.tenant_id)
            if not fresh:
                return
            fresh.status = JobStatus.queued.value
            fresh.next_run_at = datetime.now(timezone.utc) + timedelta(
                seconds=PER_TENANT_DEFER_SECONDS
            )
            fresh.lease_expires_at = None
            fresh.lease_owner = None
            db.add(fresh)
            await db.commit()
        logger.info(
            "Job %s deferred: tenant %s is at its in-flight cap in lane %s",
            job.id,
            job.tenant_id,
            self.lane,
        )

    async def _get_job_for_update(self, db: AsyncSession, job_id: str, tenant_id: str) -> Job | None:
        from sqlalchemy import select
        result = await db.execute(
            select(Job).where(Job.id == job_id, Job.tenant_id == tenant_id).with_for_update()
        )
        return result.scalar_one_or_none()

    async def _complete_in(self, db: AsyncSession, db_job: Job, result: dict | None) -> None:
        """Record a terminal success on the caller's session and commit it."""
        await complete_job(db, job=db_job, result=result)
        # Emit job.succeeded event to outbox (atomic with the job commit).
        await enqueue_event_in(
            db,
            event_type="job.succeeded",
            payload={"job_id": db_job.id, "lane": db_job.lane, "result": result},
            topic=f"{db_job.lane}-dispatch",
        )
        await db.commit()

    async def _complete(self, db_job: Job, result: dict | None) -> None:
        async with async_session() as db:
            fresh = await self._get_job_for_update(db, db_job.id, db_job.tenant_id)
            if not fresh:
                return
            await self._complete_in(db, fresh, result)

    async def _fail(self, db_job: Job, error: Exception) -> None:
        error_str = str(error)[:500]
        error_code = type(error).__name__

        async with async_session() as db:
            fresh = await self._get_job_for_update(db, db_job.id, db_job.tenant_id)
            if not fresh:
                return

            # Reconciliation: if external_intent is set and no external_result,
            # a crash happened mid-call. Log for operator review.
            if fresh.external_intent and not fresh.external_result:
                logger.warning(
                    "Job %s may have partial external side effects: intent=%s",
                    fresh.id, fresh.external_intent,
                )

            await retry_job(
                db,
                job=fresh,
                error=error_str,
                backoff_seconds=min(2 ** fresh.attempts, 300),
            )
            await enqueue_event_in(
                db,
                event_type="job.failed",
                payload={"job_id": fresh.id, "lane": fresh.lane, "error": error_str, "code": error_code},
                topic=f"{fresh.lane}-dispatch",
            )
            await db.commit()

"""Unified job runner — lane consumer loop.

Claims jobs from Postgres (FOR UPDATE SKIP LOCKED), runs the handler,
records outcome, then commits the Kafka offset. One runner per lane.
See docs/specs/2026-10-10-unified-job-processing-design.md §C.4 / §D.5
"""

import asyncio
import json
import logging
from datetime import datetime, timezone

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

# Poll interval when no work is available (seconds).
IDLE_POLL_SECONDS = 2


class JobRunner:
    """Single-lane job consumer loop.

    Run one instance per lane per worker replica. Multiple replicas safe:
    claims use FOR UPDATE SKIP LOCKED, leases expire and are reclaimed.
    """

    def __init__(self, lane: str, worker_id: str | None = None):
        self.lane = lane
        self.worker_id = worker_id or f"{lane}-worker-{id(self)}"
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
            mark_kafka_unavailable()

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
                return

        async with async_session() as db:
            # Re-fetch for update to ensure we have the latest state.
            db_job = await self._get_job_for_update(db, job.id, job.tenant_id)
            if not db_job:
                return  # claimed by another worker or cancelled

            # Idempotency: if already terminal, skip.
            if db_job.status in (JobStatus.succeeded.value, JobStatus.failed.value, JobStatus.dead.value, JobStatus.cancelled.value):
                return

            # Write external_intent BEFORE the external call (crash recovery).
            external_intent = {
                "job_type": db_job.job_type,
                "lane": db_job.lane,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "attempt": db_job.attempts + 1,
            }
            db_job.external_intent = external_intent
            db_job.status = JobStatus.running.value
            db_job.lease_owner = self.worker_id
            db_job.lease_expires_at = datetime.now(timezone.utc)  # will be set by claim
            await db.flush()

        try:
            result = await handler(db_job, db)
            await self._complete(db_job, result)
        except Exception as e:
            await self._fail(db_job, e)

    async def _get_job_for_update(self, db: AsyncSession, job_id: str, tenant_id: str) -> Job | None:
        from sqlalchemy import select
        result = await db.execute(
            select(Job).where(Job.id == job_id, Job.tenant_id == tenant_id).with_for_update()
        )
        return result.scalar_one_or_none()

    async def _complete(self, db_job: Job, result: dict | None) -> None:
        async with async_session() as db:
            fresh = await self._get_job_for_update(db, db_job.id, db_job.tenant_id)
            if not fresh:
                return
            await complete_job(db, job=fresh, result=result)
            # Emit job.succeeded event to outbox (atomic with job commit).
            await enqueue_event_in(
                db,
                event_type="job.succeeded",
                payload={"job_id": fresh.id, "lane": fresh.lane, "result": result},
                topic=f"{fresh.lane}-dispatch",
            )

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

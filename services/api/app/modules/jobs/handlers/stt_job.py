"""STT job handler — Phase 1 migration target.

No external side effects yet (provider stub). Marks the domain STTJob row.
Safe first migration: no provider calls, idempotent by job id.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....modules.stt.models import STTJob
from ...jobs.models import Job

logger = logging.getLogger(__name__)


async def handle_stt_job(job: Job, db: AsyncSession) -> dict | None:
    """Process an STT job.

    Returns a result dict to persist on Job.result, or None.
    Raises on transient failure so the runner retries.
    """
    payload = job.payload or {}
    stt_job_id = payload.get("stt_job_id")
    if not stt_job_id:
        raise ValueError("stt_job_id missing from payload")

    result = await db.execute(select(STTJob).where(STTJob.id == stt_job_id))
    stt_job = result.scalar_one_or_none()
    if not stt_job:
        raise ValueError(f"STT job {stt_job_id} not found")

    # Idempotency: already completed
    if stt_job.status == "completed":
        return {"status": "already_completed", "text": stt_job.text}

    # TODO: dispatch to real STT provider (Whisper / Azure / etc.)
    # For Phase 1, mark completed without external call — safe to migrate.
    stt_job.status = "completed"
    stt_job.completed_at = datetime.now(timezone.utc)
    db.add(stt_job)

    return {
        "status": "completed",
        "stt_job_id": stt_job_id,
        "text": stt_job.text,
    }

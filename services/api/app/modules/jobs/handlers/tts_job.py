"""TTS job handler — Phase 1 migration target.

No external side effects yet (provider stub). Marks the domain TTSJob row.
Safe first migration: no provider calls, idempotent by job id.
"""

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....modules.tts.models import TTSJob
from ...jobs.models import Job

logger = logging.getLogger(__name__)


async def handle_tts_job(job: Job, db: AsyncSession) -> dict | None:
    """Process a TTS job.

    Returns a result dict to persist on Job.result, or None.
    Raises on transient failure so the runner retries.
    """
    payload = job.payload or {}
    tts_job_id = payload.get("tts_job_id")
    if not tts_job_id:
        raise ValueError("tts_job_id missing from payload")

    result = await db.execute(select(TTSJob).where(TTSJob.id == tts_job_id))
    tts_job = result.scalar_one_or_none()
    if not tts_job:
        raise ValueError(f"TTS job {tts_job_id} not found")

    # Idempotency: already completed
    if tts_job.status == "completed":
        return {"status": "already_completed", "audio_url": tts_job.audio_url}

    # TODO: dispatch to real TTS provider (ElevenLabs / Azure / etc.)
    # For Phase 1, mark completed without external call — safe to migrate.
    tts_job.status = "completed"
    tts_job.completed_at = datetime.now(timezone.utc)
    db.add(tts_job)

    return {
        "status": "completed",
        "tts_job_id": tts_job_id,
        "audio_url": tts_job.audio_url,
    }

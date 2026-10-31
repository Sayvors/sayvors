"""STT job handler — transcribes audio using faster-whisper.

General-purpose speech-to-text: any audio URL from any channel
(WhatsApp voice notes, Instagram voice messages, Facebook voice notes,
Telegram voice messages, Google voice posts, user uploads, etc.). Not
hardcoded to any platform.

Payload contract:
    {
        "stt_job_id": str,   # the STTJob row id
    }

Idempotent by job id: the same job never transcribes twice because the lane
runner checks terminal status before running.
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...stt.models import STTJob
from ...stt.provider import transcribe_audio
from ..models import Job

logger = logging.getLogger(__name__)


async def handle_stt_job(job: Job, db: AsyncSession) -> dict | None:
    """Process one STT job.

    Downloads the audio from the job's audio_url, transcribes it with
    faster-whisper, and writes the transcript + confidence + duration back
    to the STTJob row.

    Idempotent by job id: the same job never transcribes twice because the lane
    runner checks terminal status before running.
    """
    payload = job.payload or {}
    stt_job_id = payload.get("stt_job_id")
    if not stt_job_id:
        raise ValueError("stt_job_id missing from payload")

    stt_job = (
        await db.execute(select(STTJob).where(STTJob.id == stt_job_id))
    ).scalar_one_or_none()
    if stt_job is None:
        raise ValueError(f"STT job {stt_job_id} not found")

    # Idempotency: already completed.
    if stt_job.status == "completed":
        return {
            "status": "already_completed",
            "stt_job_id": stt_job.id,
            "text": stt_job.text,
            "confidence": stt_job.confidence,
            "duration_ms": stt_job.duration_ms,
        }

    stt_job.status = "processing"
    db.add(stt_job)
    await db.commit()

    try:
        result = await transcribe_audio(
            audio_url=stt_job.audio_url,
            language=stt_job.language or None,
            db=db,
        )

        stt_job.status = "completed"
        stt_job.text = result["text"]
        stt_job.confidence = result["confidence"]
        stt_job.duration_ms = result["duration_ms"]
        stt_job.error = None
        stt_job.completed_at = datetime.now(timezone.utc)
        db.add(stt_job)
        await db.commit()

        logger.info(
            "STT job %s completed: %.0f ms, %.0f%% confidence, %d chars",
            stt_job.id,
            stt_job.duration_ms or 0,
            (stt_job.confidence or 0) * 100,
            len(stt_job.text or ""),
        )

        # Meter the hosted minutes (post-paid: the provider call already ran).
        # The rate card is admin-editable; a 0 rate means "not billed", so
        # this is a no-op until an operator sets one.
        try:
            from ...billing import pricing

            await pricing.ensure_fresh(db)
            cents = pricing.asr_cost_cents(stt_job.duration_ms)
            charged = await pricing.charge_voice(
                stt_job.user_id,
                cents,
                purpose=f"stt {stt_job.duration_ms or 0}ms",
                idempotency_key=f"asr:{stt_job.id}",
            )
            if charged:
                logger.info(
                    "STT job %s billed %d cents (tenant %s)",
                    stt_job.id, charged, stt_job.user_id,
                )
        except Exception as e:  # noqa: BLE001 - billing never breaks the job
            logger.warning("STT job %s metering failed: %s", stt_job.id, e)

        return {
            "status": "completed",
            "stt_job_id": stt_job.id,
            "text": stt_job.text,
            "confidence": stt_job.confidence,
            "duration_ms": stt_job.duration_ms,
        }

    except Exception as e:  # noqa: BLE001 — transcribe failures are job failures
        logger.error("STT job %s failed: %s", stt_job.id, e)
        stt_job.status = "failed"
        stt_job.error = str(e)[:500]
        stt_job.completed_at = datetime.now(timezone.utc)
        db.add(stt_job)
        await db.commit()
        raise
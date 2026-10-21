"""TTS job handler — renders text with the platform TTS capability.

Payload contract:
    {
        "tts_job_id": str,   # the TTSJob row id
    }

The capability owns engine selection, provider dispatch and metering. This
handler owns the job lifecycle: status, the stored artifact, and the error
text the tenant sees. It is idempotent by job id — a rerun after a crash
re-renders into the same private key instead of creating a second artifact.

A provider that returns no audio is a deterministic failure (no engine
covers the language, or the provider refused): the row is marked failed and
the unified Job succeeds, so the runner does not retry a request that will
fail again and charge the tenant each time. Storage errors are infrastructural
and are raised so the runner retries with backoff.
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....core.storage import put_doc
from ...tts.api import AudioFormat, SynthesisRequest, VoiceRef, synthesize
from ...tts.models import TTSJob
from ..models import Job

logger = logging.getLogger(__name__)

# Container -> file extension. The mime type comes back from the engine (or
# from ffmpeg after conversion), so the key follows what was actually stored.
_AUDIO_EXT = {
    "audio/mpeg": "mp3",
    "audio/ogg": "ogg",
    "audio/opus": "ogg",
    "audio/wav": "wav",
    "audio/x-wav": "wav",
    "audio/pcm": "pcm",
}


def _storage_filename(tts_job_id: str, mime_type: str) -> str:
    return f"tts/{tts_job_id}.{_AUDIO_EXT.get(mime_type, 'bin')}"


async def handle_tts_job(job: Job, db: AsyncSession) -> dict | None:
    """Render one TTS job and store the audio under the tenant's private docs.

    Returns a result dict to persist on Job.result, or None.
    """
    payload = job.payload or {}
    tts_job_id = payload.get("tts_job_id")
    if not tts_job_id:
        raise ValueError("tts_job_id missing from payload")

    tts_job = (
        await db.execute(select(TTSJob).where(TTSJob.id == tts_job_id))
    ).scalar_one_or_none()
    if tts_job is None:
        raise ValueError(f"TTS job {tts_job_id} not found")

    # Idempotency: a row with an artifact is done. A row marked completed
    # without one is the legacy fake-success path; re-render it rather than
    # report audio that does not exist.
    if tts_job.status == "completed" and tts_job.storage_key:
        return {
            "status": "already_completed",
            "tts_job_id": tts_job.id,
            "audio_url": tts_job.audio_url,
        }

    tts_job.status = "processing"
    tts_job.error = None
    db.add(tts_job)
    # Commit before the provider call so a slow engine never holds the
    # transaction (or a connection) open.
    await db.commit()

    request = SynthesisRequest(
        text=tts_job.text,
        language=tts_job.language or "en",
        tenant_id=tts_job.user_id,
        voice=VoiceRef(tier="simple"),
        # MP3 downloads play everywhere a browser or phone might open them.
        # Channels that need Ogg/Opus or telephony PCM call synthesize()
        # directly with their own format.
        format=AudioFormat.MP3,
        speed=tts_job.speed or 1.0,
        purpose="tts.job",
    )

    try:
        result = await synthesize(request)
        if result is None:
            tts_job.status = "failed"
            tts_job.error = (
                "No voice engine could render this request. Check that an "
                "enabled engine covers the language and that its API key is valid."
            )
            tts_job.completed_at = datetime.now(timezone.utc)
            db.add(tts_job)
            await db.commit()
            logger.warning(
                "TTS job %s produced no audio language=%s chars=%d",
                tts_job.id, request.language, len(request.text),
            )
            return {
                "status": "failed",
                "tts_job_id": tts_job.id,
                "error": tts_job.error,
            }

        storage_key = _storage_filename(tts_job.id, result.mime_type)
        put_doc(tts_job.user_id, storage_key, result.audio)

        tts_job.status = "completed"
        tts_job.storage_key = storage_key
        tts_job.audio_mime = result.mime_type
        tts_job.audio_url = f"/api/v1/tts/jobs/{tts_job.id}/audio"
        tts_job.error = None
        tts_job.completed_at = datetime.now(timezone.utc)
        db.add(tts_job)
        await db.commit()

        logger.info(
            "TTS job %s completed: provider=%s voice=%s %d bytes %.0f ms",
            tts_job.id,
            result.provider,
            result.voice,
            len(result.audio),
            result.latency_ms,
        )
        return {
            "status": "completed",
            "tts_job_id": tts_job.id,
            "audio_url": tts_job.audio_url,
            "mime_type": result.mime_type,
            "provider": result.provider,
        }

    except Exception as e:
        # Storage/infrastructure failure: record it and let the runner retry.
        logger.error("TTS job %s failed: %s: %s", tts_job.id, type(e).__name__, e)
        tts_job.status = "failed"
        tts_job.error = f"{type(e).__name__}: {str(e)[:400]}"
        tts_job.completed_at = datetime.now(timezone.utc)
        try:
            db.add(tts_job)
            await db.commit()
        except Exception:
            await db.rollback()
            logger.exception("Could not record the failure of TTS job %s", tts_job.id)
        raise

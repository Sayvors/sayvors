import uuid
from datetime import datetime, timezone

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..users.models import User
from .models import TTSJob, Voice
from .schemas import TTSRequest


async def list_voices(db: AsyncSession, language: str | None = None) -> list[Voice]:
    query = select(Voice)
    if language:
        query = query.where(Voice.language == language)
    result = await db.execute(query.order_by(Voice.name))
    return list(result.scalars().all())


async def create_tts_job(
    body: TTSRequest, user: User, db: AsyncSession
) -> TTSJob:
    job = TTSJob(
        id=str(uuid.uuid4()),
        user_id=user.id,
        text=body.text,
        voice_id=body.voice_id,
        language=body.language,
        speed=body.speed,
        status="pending",
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    # TODO: dispatch to TTS provider (ElevenLabs, Azure, etc.)
    # For now, mark as completed
    job.status = "completed"
    job.completed_at = datetime.now(timezone.utc)
    await db.commit()
    return job


async def get_job(job_id: str, user: User, db: AsyncSession) -> TTSJob | None:
    result = await db.execute(
        select(TTSJob).where(TTSJob.id == job_id, TTSJob.user_id == user.id)
    )
    return result.scalar_one_or_none()


async def list_jobs(
    user: User, db: AsyncSession, limit: int = 20, offset: int = 0
) -> tuple[list[TTSJob], int]:
    count_result = await db.execute(
        select(func.count()).where(TTSJob.user_id == user.id)
    )
    total = count_result.scalar() or 0

    result = await db.execute(
        select(TTSJob)
        .where(TTSJob.user_id == user.id)
        .order_by(TTSJob.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all()), total

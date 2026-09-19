import uuid
from datetime import datetime, timezone

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..users.models import User
from .models import STTJob
from .schemas import STTRequest


async def create_stt_job(body: STTRequest, user: User, db: AsyncSession) -> STTJob:
    job = STTJob(
        id=str(uuid.uuid4()),
        user_id=user.id,
        audio_url=body.audio_url,
        language=body.language,
        status="pending",
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    # TODO: dispatch to STT provider (Whisper, Azure, etc.)
    job.status = "completed"
    job.completed_at = datetime.now(timezone.utc)
    await db.commit()
    return job


async def get_job(job_id: str, user: User, db: AsyncSession) -> STTJob | None:
    result = await db.execute(
        select(STTJob).where(STTJob.id == job_id, STTJob.user_id == user.id)
    )
    return result.scalar_one_or_none()


async def list_jobs(
    user: User, db: AsyncSession, limit: int = 20, offset: int = 0
) -> tuple[list[STTJob], int]:
    count_result = await db.execute(
        select(func.count()).where(STTJob.user_id == user.id)
    )
    total = count_result.scalar() or 0

    result = await db.execute(
        select(STTJob)
        .where(STTJob.user_id == user.id)
        .order_by(STTJob.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(result.scalars().all()), total

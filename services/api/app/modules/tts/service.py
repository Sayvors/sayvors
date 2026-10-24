import uuid

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..jobs.service import submit_job
from ..jobs.types import JobType
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
    """Persist a pending job and enqueue it on the bulk lane.

    The TTSJob row and its durable Job row commit in one transaction: a job
    the client can poll but no worker will ever see is worse than a failed
    request the client can retry.
    """
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
    await db.flush()

    unified = await submit_job(
        db,
        tenant_id=user.id,
        job_type=JobType.tts_job.value,
        payload={"tts_job_id": job.id},
        idempotency_key=f"tts:{job.id}",
        subject_type="tts_job",
        subject_id=job.id,
    )
    job.job_id = unified.id
    db.add(job)
    await db.commit()
    await db.refresh(job)
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

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..jobs.service import submit_job
from ..jobs.types import JobType
from ..team.context import tenant_id_of
from ..users.models import User
from .models import STTJob
from .schemas import STTRequest


async def create_stt_job(body: STTRequest, user: User, db: AsyncSession) -> STTJob:
    """Persist the request and queue the transcription.

    The STTJob row and the durable Job commit together: a job the client can
    poll but no worker will ever see is worse than a failed request the client
    can retry. Same contract as the TTS job.
    """
    job = STTJob(
        id=str(uuid.uuid4()),
        user_id=user.id,
        audio_url=body.audio_url,
        language=body.language,
        status="pending",
    )
    db.add(job)
    await db.flush()

    unified = await submit_job(
        db,
        tenant_id=tenant_id_of(user),
        job_type=JobType.stt_job.value,
        payload={"stt_job_id": job.id},
        idempotency_key=f"stt:{job.id}",
        subject_type="stt_job",
        subject_id=job.id,
    )
    job.job_id = unified.id
    db.add(job)
    await db.commit()
    await db.refresh(job)
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

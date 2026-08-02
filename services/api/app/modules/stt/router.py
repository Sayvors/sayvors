from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.deps import get_db, get_current_user
from ..users.models import User
from .schemas import STTJobListResponse, STTJobResponse, STTRequest
from .service import create_stt_job, get_job, list_jobs

router = APIRouter(prefix="/api/v1/stt", tags=["stt"])


@router.post("/transcribe", response_model=STTJobResponse, status_code=status.HTTP_201_CREATED)
async def transcribe_audio(
    body: STTRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    job = await create_stt_job(body, user, db)
    return STTJobResponse(
        id=job.id,
        status=job.status,
        text=job.text,
        confidence=job.confidence,
        duration_ms=job.duration_ms,
        error=job.error,
        created_at=job.created_at.isoformat(),
    )


@router.get("/jobs", response_model=STTJobListResponse)
async def get_jobs(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    jobs, total = await list_jobs(user, db, limit, offset)
    return STTJobListResponse(
        jobs=[
            STTJobResponse(
                id=j.id,
                status=j.status,
                text=j.text,
                confidence=j.confidence,
                duration_ms=j.duration_ms,
                error=j.error,
                created_at=j.created_at.isoformat(),
            )
            for j in jobs
        ],
        total=total,
    )


@router.get("/jobs/{job_id}", response_model=STTJobResponse)
async def get_job_by_id(
    job_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    job = await get_job(job_id, user, db)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return STTJobResponse(
        id=job.id,
        status=job.status,
        text=job.text,
        confidence=job.confidence,
        duration_ms=job.duration_ms,
        error=job.error,
        created_at=job.created_at.isoformat(),
    )

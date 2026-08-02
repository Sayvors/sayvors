from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.deps import get_db
from ...core.deps import get_current_user
from ..users.models import User
from .schemas import TTSJobListResponse, TTSJobResponse, TTSRequest, VoiceResponse
from .service import create_tts_job, get_job, list_jobs, list_voices

router = APIRouter(prefix="/api/v1/tts", tags=["tts"])


@router.get("/voices", response_model=list[VoiceResponse])
async def get_voices(
    language: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    return await list_voices(db, language)


@router.post("/convert", response_model=TTSJobResponse, status_code=status.HTTP_201_CREATED)
async def convert_text_to_speech(
    body: TTSRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    job = await create_tts_job(body, user, db)
    return TTSJobResponse(
        id=job.id,
        status=job.status,
        audio_url=job.audio_url,
        duration_ms=job.duration_ms,
        error=job.error,
        created_at=job.created_at.isoformat(),
    )


@router.get("/jobs", response_model=TTSJobListResponse)
async def get_jobs(
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    jobs, total = await list_jobs(user, db, limit, offset)
    return TTSJobListResponse(
        jobs=[
            TTSJobResponse(
                id=j.id,
                status=j.status,
                audio_url=j.audio_url,
                duration_ms=j.duration_ms,
                error=j.error,
                created_at=j.created_at.isoformat(),
            )
            for j in jobs
        ],
        total=total,
    )


@router.get("/jobs/{job_id}", response_model=TTSJobResponse)
async def get_job_by_id(
    job_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    job = await get_job(job_id, user, db)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return TTSJobResponse(
        id=job.id,
        status=job.status,
        audio_url=job.audio_url,
        duration_ms=job.duration_ms,
        error=job.error,
        created_at=job.created_at.isoformat(),
    )

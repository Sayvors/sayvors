"""Job queue API — submit, status, cancel, and admin operations.

Client-facing endpoints use /api/v1/jobs. Admin endpoints use
/api/v1/admin/jobs.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.deps import get_current_user, get_db, require_admin
from ..team.context import tenant_id_of
from . import service
from .models import Job

router = APIRouter(prefix="/api/v1", tags=["jobs"])
admin_router = APIRouter(prefix="/api/v1/admin", tags=["admin-jobs"])


def _job_to_dict(job: Job) -> dict:
    return {
        "id": job.id,
        "tenant_id": job.tenant_id,
        "job_type": job.job_type,
        "lane": job.lane,
        "status": job.status,
        "priority": job.priority,
        "attempts": job.attempts,
        "max_attempts": job.max_attempts,
        "next_run_at": job.next_run_at.isoformat() if job.next_run_at else None,
        "hard_deadline_at": job.hard_deadline_at.isoformat() if job.hard_deadline_at else None,
        "lease_owner": job.lease_owner,
        "lease_expires_at": job.lease_expires_at.isoformat() if job.lease_expires_at else None,
        "error_code": job.error_code,
        "last_error": job.last_error,
        "result": job.result,
        "subject_type": job.subject_type,
        "subject_id": job.subject_id,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
    }


# ── Client-facing ──────────────────────────────────────────────────


@router.post("/jobs", status_code=202)
async def submit_job_endpoint(
    body: dict,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Submit a job. Returns 202 with job_id for polling."""
    job_type = body.get("job_type") or body.get("type")
    if not job_type:
        raise HTTPException(status_code=400, detail="job_type is required")
    tenant_id = tenant_id_of(user)
    try:
        job = await service.submit_job(
            db,
            tenant_id=tenant_id,
            job_type=job_type,
            payload=body.get("payload", {}),
            lane=body.get("lane"),
            priority=body.get("priority", 50),
            max_attempts=body.get("max_attempts"),
            idempotency_key=body.get("idempotency_key"),
            subject_type=body.get("subject_type"),
            subject_id=body.get("subject_id"),
            lane_key=body.get("lane_key"),
        )
        await db.commit()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"job_id": job.id, "status": job.status, "lane": job.lane}


@router.get("/jobs/{job_id}")
async def get_job_endpoint(
    job_id: str,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get job status, progress, result, and error."""
    tenant_id = tenant_id_of(user)
    job = await service.get_job(db, job_id, tenant_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return _job_to_dict(job)


@router.get("/jobs")
async def list_jobs_endpoint(
    status: str | None = Query(None),
    lane: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List jobs for the current tenant."""
    tenant_id = tenant_id_of(user)
    jobs = await service.list_jobs(db, tenant_id=tenant_id, status=status, lane=lane, limit=limit)
    return [_job_to_dict(j) for j in jobs]


@router.post("/jobs/{job_id}/cancel")
async def cancel_job_endpoint(
    job_id: str,
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Cancel a queued or retrying job."""
    tenant_id = tenant_id_of(user)
    job = await service.get_job(db, job_id, tenant_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    cancelled = await service.cancel_job(db, job=job)
    await db.commit()
    if not cancelled:
        raise HTTPException(status_code=409, detail=f"Job cannot be cancelled in status '{job.status}'")
    return {"job_id": job.id, "status": job.status}


# ── Admin ──────────────────────────────────────────────────────────


@admin_router.get("/jobs")
async def admin_list_jobs(
    status: str | None = Query(None),
    lane: str | None = Query(None),
    tenant_id: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    _admin: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """List all jobs (admin). Filter by status, lane, tenant."""
    from sqlalchemy import select

    stmt = select(Job).order_by(Job.created_at.desc()).limit(limit)
    if status:
        stmt = stmt.where(Job.status == status)
    if lane:
        stmt = stmt.where(Job.lane == lane)
    if tenant_id:
        stmt = stmt.where(Job.tenant_id == tenant_id)
    result = await db.execute(stmt)
    return [_job_to_dict(j) for j in result.scalars().all()]


@admin_router.get("/jobs/{job_id}")
async def admin_get_job(
    job_id: str,
    _admin: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Get job detail (admin, any tenant)."""
    from sqlalchemy import select

    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return _job_to_dict(job)


@admin_router.post("/jobs/{job_id}/replay")
async def admin_replay_job(
    job_id: str,
    _admin: dict = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Replay a dead or failed job: reset to queued with attempts=0."""
    from sqlalchemy import select

    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    replayed = await service.replay_job(db, job_id=job_id, tenant_id=job.tenant_id)
    if replayed is None:
        raise HTTPException(status_code=409, detail=f"Job cannot be replayed in status '{job.status}'")
    await db.commit()
    return _job_to_dict(replayed)

"""Job queue API — submit, status, cancel, and admin operations.

Client-facing endpoints use /api/v1/jobs. Admin endpoints use
/api/v1/admin/jobs.
"""
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.deps import get_current_user, get_db, require_admin
from ..team.context import TenantContext, require_perm, tenant_id_of
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
        "progress": getattr(job, "progress", 0) or 0,
        "progress_label": getattr(job, "progress_label", None),
        "ui_title": getattr(job, "ui_title", None),
        "ui_kind": getattr(job, "ui_kind", None),
        "ui_visible": bool(getattr(job, "ui_visible", False)),
        "ui_subject_type": getattr(job, "ui_subject_type", None),
        "ui_subject_id": getattr(job, "ui_subject_id", None),
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
    }


# ── Client-facing ──────────────────────────────────────────────────


@router.post("/jobs", status_code=202)
async def submit_job_endpoint(
    body: dict,
    ctx: TenantContext = Depends(require_perm("settings.manage")),
    db: AsyncSession = Depends(get_db),
):
    """Submit a job for the caller's own tenant. Returns 202 with job_id.

    This is an operator surface, not a customer one: internal features submit
    their jobs from the domain service (which already resolved the tenant and
    the lane), so an arbitrary authenticated user must not be able to enqueue
    work. Lane, priority and retry budget are server-controlled - accepting
    them from the client would let a caller starve or flood a lane.
    """
    job_type = body.get("job_type") or body.get("type")
    if not job_type:
        raise HTTPException(status_code=400, detail="job_type is required")
    # Reject registry types that have no handler: enqueuing them would burn
    # retries and end as `no_handler` without doing any work.
    from .handlers import HANDLERS

    if job_type not in HANDLERS:
        raise HTTPException(
            status_code=400, detail=f"job_type cannot be submitted: {job_type}"
        )
    payload = body.get("payload") or {}
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="payload must be an object")
    try:
        job = await service.submit_job(
            db,
            tenant_id=ctx.tenant_id,
            job_type=job_type,
            payload=payload,
            idempotency_key=body.get("idempotency_key"),
            subject_type=body.get("subject_type"),
            subject_id=body.get("subject_id"),
            lane_key=body.get("lane_key"),
        )
        await db.commit()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"job_id": job.id, "status": job.status, "lane": job.lane}


@router.get("/jobs/active-ui")
async def list_active_ui_jobs_endpoint(
    response: Response,
    limit: int = Query(20, ge=1, le=20),
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
    user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Tenant-scoped in-flight UI jobs for the background progress panel."""
    import hashlib, json as _json

    tenant_id = tenant_id_of(user)
    jobs = await service.list_active_ui_jobs(db, tenant_id=tenant_id, limit=limit)
    payload = [_job_to_dict(j) for j in jobs]
    etag_src = _json.dumps(
        [(j["id"], j["status"], j["progress"], j["updated_at"]) for j in payload],
        separators=(",", ":"),
        sort_keys=True,
    )
    etag = '"' + hashlib.sha256(etag_src.encode("utf-8")).hexdigest()[:32] + '"'
    response.headers["ETag"] = etag
    response.headers["Cache-Control"] = "private, no-cache"
    if if_none_match == etag:
        response.status_code = 304
        return Response(status_code=304, headers={"ETag": etag, "Cache-Control": "private, no-cache"})
    return payload


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
    """List all jobs (admin). Filter by status, lane, tenant.

    Tenant email/business name is joined in so the queue is readable without
    decoding raw ids.
    """
    from sqlalchemy import select

    from ..users.models import User

    stmt = select(Job).order_by(Job.created_at.desc()).limit(limit)
    if status:
        stmt = stmt.where(Job.status == status)
    if lane:
        stmt = stmt.where(Job.lane == lane)
    if tenant_id:
        stmt = stmt.where(Job.tenant_id == tenant_id)
    jobs = (await db.execute(stmt)).scalars().all()

    tenant_ids = {j.tenant_id for j in jobs}
    emails: dict[str, str] = {}
    if tenant_ids:
        user_rows = (
            await db.execute(select(User.id, User.email).where(User.id.in_(tenant_ids)))
        ).all()
        emails = {str(uid): str(email) for uid, email in user_rows}

    out = []
    for job in jobs:
        d = _job_to_dict(job)
        d["tenant_email"] = emails.get(job.tenant_id)
        out.append(d)
    return out


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

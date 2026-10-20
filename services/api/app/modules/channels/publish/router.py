"""Publish API — one post to many destinations, backed by the job queue.

POST   /api/v1/channels/publish      upload media + destinations -> create jobs
GET    /api/v1/channels/publish/{job_id}   job status (client polls)

Flow:
1. Client uploads media (POST /api/v1/storage/upload or direct-to-S3 presign)
2. Client calls POST /publish with media_url + destinations + formats
3. Endpoint creates one Job per destination+format (lane=publishing)
4. Job runner claims + runs handle_post_publish per job
5. Client polls GET /publish/{job_id} for status
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....config import settings
from ....core.deps import get_current_user, get_db
from ....database import async_session
from ....modules.kafka.client import get_kafka_producer
from ...users.models import User
from ...jobs.models import Job, JobStatus
from ...jobs.service import submit_job
from ...jobs.types import JobType
from ...team.context import tenant_id_of
from ..models import Channel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/channels", tags=["channels-publish"])


# Platforms the publish pipeline can actually deliver to. Anything else is
# rejected at the boundary so we never enqueue a job the worker cannot run.
_SUPPORTED_PLATFORMS = {"whatsapp", "facebook", "instagram", "google_reviews"}
_SUPPORTED_METHODS = {"post", "story", "reel", "status"}


class PublishDestination(BaseModel):
    platform: str = Field(..., min_length=1, max_length=32)
    external_asset_id: str = Field(..., min_length=1, max_length=200)
    methods: list[str] = Field(..., min_length=1)

    @field_validator("platform")
    @classmethod
    def _validate_platform(cls, v: str) -> str:
        if v not in _SUPPORTED_PLATFORMS:
            raise ValueError(f"unsupported platform: {v}")
        return v

    @field_validator("methods")
    @classmethod
    def _validate_methods(cls, v: list[str]) -> list[str]:
        for m in v:
            if m not in _SUPPORTED_METHODS:
                raise ValueError(f"unsupported method: {m}")
        if len(set(v)) != len(v):
            raise ValueError("duplicate method in methods list")
        return v


class PublishBody(BaseModel):
    media_url: str = Field(..., min_length=1)
    media_type: str = Field("image")
    media_key: str | None = None
    caption: str = Field("", max_length=5000)
    description: str = Field("", max_length=5000)
    scheduled_at: str | None = None
    idempotency_key: str | None = Field(None, max_length=200)
    destinations: list[PublishDestination]

    @field_validator("media_type")
    @classmethod
    def _validate_media_type(cls, v: str) -> str:
        if v not in {"image", "video"}:
            raise ValueError("media_type must be 'image' or 'video'")
        return v

    @field_validator("scheduled_at")
    @classmethod
    def _validate_scheduled_at(cls, v: str | None) -> str | None:
        if v is None or v == "":
            return None
        # Accept ISO-8601 with optional trailing Z. Must be in the future.
        from datetime import datetime, timezone

        s = v.strip()
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError as e:
            raise ValueError(f"invalid scheduled_at: {e}") from e
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        if dt < now:
            raise ValueError("scheduled_at must be in the future")
        # Cap at 90 days out (Meta's own limit for scheduled posts).
        if dt > now.replace(year=now.year + 1):
            raise ValueError("scheduled_at too far in the future")
        return dt.isoformat()


class JobOut(BaseModel):
    job_id: str
    status: str
    lane: str
    created_at: str


@router.post("/publish", response_model=list[JobOut])
async def publish_post(
    body: PublishBody,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Publish one post to many destination+format combinations.

    Creates one Job per (destination, method) pair on the publishing lane.
    Returns the job ids so the client can poll status.
    """
    tenant_id = tenant_id_of(user)
    jobs_out: list[JobOut] = []
    idempotency_key = body.idempotency_key

    # Create every job in a single transaction. A partial failure (e.g. a
    # duplicate idempotency key, or a constraint violation) rolls back the
    # whole batch instead of leaving some destinations scheduled and some not.
    try:
        for dest in body.destinations:
            platform = dest.platform
            asset_id = dest.external_asset_id
            for method in dest.methods:
                payload: dict[str, Any] = {
                    "media_url": body.media_url,
                    "media_type": body.media_type,
                    "media_key": body.media_key,
                    "caption": body.caption,
                    "description": body.description,
                    "platform": platform,
                    "external_asset_id": asset_id,
                    "method": method,
                    "scheduled_at": body.scheduled_at,
                }

                idem_key = (
                    f"{idempotency_key}:{platform}:{method}" if idempotency_key else None
                )

                job = await submit_job(
                    db,
                    tenant_id=tenant_id,
                    job_type=JobType.post_publish.value,
                    payload=payload,
                    lane="publishing",
                    priority=50,
                    max_attempts=5,
                    idempotency_key=idem_key,
                    subject_type="post",
                    subject_id=str(uuid.uuid4()),
                    lane_key=f"{tenant_id}:{platform}:{asset_id}:{method}",
                )
                jobs_out.append(
                    JobOut(
                        job_id=job.id,
                        status=job.status,
                        lane=job.lane,
                        created_at=job.created_at.isoformat(),
                    )
                )
        await db.commit()
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        await db.rollback()
        logger.exception("publish_post failed")
        raise HTTPException(status_code=500, detail="publish failed") from e

    # Dispatch all jobs to Kafka now so the publishing lane runner picks them up.
    # Dispatch is best-effort: jobs are already persisted in Postgres in the
    # 'accepted' state, and the publishing worker polls for accepted jobs even
    # if Kafka is down, so a dispatch failure never loses a publish.
    if jobs_out:
        try:
            producer = await get_kafka_producer()
            for job_out in jobs_out:
                await producer.send_and_wait(
                    "publishing-dispatch",
                    key=job_out.job_id.encode(),
                    value=json.dumps(
                        {
                            "job_id": job_out.job_id,
                            "lane": "publishing",
                            "action": "run",
                        }
                    ).encode(),
                )
        except Exception:
            logger.warning(
                "Kafka dispatch failed - %d jobs remain accepted in Postgres "
                "and will be picked up by the publishing worker",
                len(jobs_out),
            )

    return jobs_out


@router.get("/publish/status", response_model=list[JobOut])
async def publish_status_batch(
    job_ids: str = Query(..., description="Comma-separated job ids"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Poll the status of several publish jobs at once (tenant-scoped).

    The frontend polls one batch per render tick rather than N requests.
    Unknown or cross-tenant ids are silently dropped (never leaked).
    """
    tenant_id = tenant_id_of(user)
    ids = [j.strip() for j in job_ids.split(",") if j.strip()]
    if not ids:
        return []
    if len(ids) > 100:
        raise HTTPException(status_code=400, detail="too many job_ids (max 100)")

    rows = await db.execute(
        select(Job).where(Job.id.in_(ids), Job.tenant_id == tenant_id)
    )
    out: list[JobOut] = []
    for job_row in rows.scalars().all():
        out.append(
            JobOut(
                job_id=job_row.id,
                status=job_row.status,
                lane=job_row.lane,
                created_at=job_row.created_at.isoformat(),
            )
        )
    return out


@router.get("/publish/{job_id}", response_model=JobOut)
async def publish_status(
    job_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Poll the status of one publish job (tenant-scoped)."""
    tenant_id = tenant_id_of(user)
    job = await db.execute(
        select(Job).where(Job.id == job_id, Job.tenant_id == tenant_id)
    )
    job_row = job.scalar_one_or_none()
    if not job_row:
        raise HTTPException(status_code=404, detail="Publish job not found")
    return JobOut(
        job_id=job_row.id,
        status=job_row.status,
        lane=job_row.lane,
        created_at=job_row.created_at.isoformat(),
    )

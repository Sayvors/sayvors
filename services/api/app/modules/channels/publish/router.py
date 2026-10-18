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
from pydantic import BaseModel, Field
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


class PublishDestination(BaseModel):
    platform: str = Field(..., min_length=1, max_length=32)
    external_asset_id: str = Field(..., min_length=1, max_length=200)
    methods: list[str] = Field(..., min_length=1)


class PublishBody(BaseModel):
    media_url: str = Field(..., min_length=1)
    media_type: str = Field("image")
    media_key: str | None = None
    caption: str = Field("", max_length=5000)
    description: str = Field("", max_length=5000)
    scheduled_at: str | None = None
    idempotency_key: str | None = Field(None, max_length=200)
    destinations: list[PublishDestination]


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

    now = datetime.now(timezone.utc)

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

            idem_key = body.idempotency_key
            if idem_key:
                idem_key = f"{idem_key}:{platform}:{method}"

            try:
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
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e)) from e

            await db.commit()
            jobs_out.append(
                JobOut(
                    job_id=job.id,
                    status=job.status,
                    lane=job.lane,
                    created_at=job.created_at.isoformat(),
                )
            )

    # Dispatch all jobs to Kafka now so the publishing lane runner picks them up.
    try:
        producer = await get_kafka_producer()
        for job_out in jobs_out:
            await producer.send_and_wait(
                "publishing-dispatch",
                key=jobs_out[jobs_out.index(job_out)].job_id.encode() if False else b"",
                value=json.dumps(
                    {
                        "job_id": job_out.job_id,
                        "lane": "publishing",
                        "action": "run",
                    }
                ).encode(),
            )
    except Exception:
        # Kafka down: jobs sit in Postgres accepted state; the runner retries
        # topic provisioning + producer on its next tick.
        logger.warning("Kafka dispatch failed — jobs remain queued in Postgres")

    return jobs_out


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

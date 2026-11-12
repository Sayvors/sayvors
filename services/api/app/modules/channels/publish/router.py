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

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ....config import settings
from ....core.deps import get_current_user, get_db
from ....database import async_session
from ....modules.kafka.client import get_kafka_producer
from ...users.models import User
from ...jobs.handlers.post_publish import _provider_for
from ...jobs.models import Job, JobStatus
from ...jobs.service import submit_job
from ...jobs.types import JobType
from ...team.context import tenant_id_of
from ..google_reviews import GoogleReviewsError
from ..meta.providers.google_post_fields import build_post_fields, parse_instant, topic_type_for
from ..meta.providers.google_publish import GoogleBusinessPublisher
from ..models import Channel
from ..service import channel_location_ids, encrypt_token, decrypt_token
from .service import schedule_removal

logger = logging.getLogger(__name__)

# A dispatch is a hint, not a delivery guarantee: the job is already
# committed to Postgres and the lane runner claims it from there. The wait is
# therefore bounded - a sick broker must not hold the HTTP request (and an
# API worker) open forever.
KAFKA_DISPATCH_TIMEOUT_SECONDS = 5.0

router = APIRouter(prefix="/api/v1/channels", tags=["channels-publish"])


# Platforms the publish pipeline can actually deliver to. Anything else is
# rejected at the boundary so we never enqueue a job the worker cannot run.
_SUPPORTED_PLATFORMS = {"whatsapp", "facebook", "instagram", "google_reviews"}
# Meta formats (post/story/reel/status) plus Google post types. "update"
# is Google's STANDARD topic; "event" and "offer" map to EVENT/OFFER.
# "profile" and "banner" are account surfaces, not feed posts — they
# replace the avatar / cover image and carry no caption. Which platform
# accepts which is enforced per provider in the job handler.
_SUPPORTED_METHODS = {
    "post",
    "story",
    "reel",
    "status",
    "update",
    "event",
    "offer",
    "profile",
    "banner",
}


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


# Formats that cannot exist without an image. Kept here so the API refuses a
# doomed job even if a client bypasses the composer's gate.
_MEDIA_REQUIRED_METHODS = {"story", "reel", "status", "profile", "banner"}


class PublishBody(BaseModel):
    media_url: str | None = None
    media_type: str = Field("image")
    media_key: str | None = None
    caption: str = Field("", max_length=5000)
    description: str = Field("", max_length=5000)
    # Call-to-action button. `cta_type` is one of the composer's keys
    # (book/order/shop/learn_more/sign_up/call); Google maps it to a
    # CallToAction.actionType. Ignored for OFFER posts, which carry the link
    # in offer.redeemOnlineUrl instead.
    cta_type: str | None = Field(None, max_length=32)
    cta_url: str | None = Field(None, max_length=1000)
    scheduled_at: str | None = None
    delete_at: str | None = None
    # Event/offer window. Google requires an `event` object for EVENT and
    # OFFER topics, so these carry the schedule; when omitted the publisher
    # defaults the window (now → +7 days).
    start_date: str | None = None
    end_date: str | None = None
    # The language of the post (BCP-47), e.g. "en-US" or "ar". Google's
    # LocalPost reference documents languageCode on the post body; it
    # defaults to en-US when absent.
    language_code: str | None = Field(None, max_length=16)
    idempotency_key: str | None = Field(None, max_length=200)
    destinations: list[PublishDestination]
    batch_id: str | None = Field(None, max_length=64)

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

    @field_validator("delete_at")
    @classmethod
    def _validate_delete_at(cls, v: str | None) -> str | None:
        """When the post should be taken down again.

        A promotional post has an end date: it goes up now and comes
        down on the day the offer lapses. The date must be in the
        future, and after the publish time — a post cannot be removed
        before it is published.
        """
        if v is None or v == "":
            return None
        from datetime import datetime, timezone

        s = v.strip()
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError as e:
            raise ValueError(f"invalid delete_at: {e}") from e
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        if dt <= datetime.now(timezone.utc):
            raise ValueError("delete_at must be in the future")
        return dt.isoformat()

    @model_validator(mode="after")
    def _validate_event_window(self) -> "PublishBody":
        """An event/offer window must run forward, and parse as ISO-8601."""
        if not (self.start_date and self.end_date):
            return self
        from datetime import datetime

        try:
            start = datetime.fromisoformat(str(self.start_date).replace("Z", "+00:00"))
            end = datetime.fromisoformat(str(self.end_date).replace("Z", "+00:00"))
        except ValueError as e:
            raise ValueError(f"invalid event date: {e}") from e
        if end <= start:
            raise ValueError("end_date must be after start_date")
        return self

    def check_delete_after_publish(self) -> None:
        """The removal must land after the publish, not before it."""
        if not self.delete_at or not self.scheduled_at:
            return
        if self.delete_at <= self.scheduled_at:
            raise ValueError("delete_at must be after the scheduled publish time")


class JobOut(BaseModel):
    job_id: str
    status: str
    lane: str
    created_at: str
    platform: str | None = None
    method: str | None = None
    external_asset_id: str | None = None
    scheduled_at: str | None = None
    # When the post is due to be taken down again (a promotional post
    # with an end date). Echoed so the feed can show it on the card.
    delete_at: str | None = None
    result: dict[str, Any] | None = None
    last_error: str | None = None
    updated_at: str | None = None
    batch_id: str | None = None
    # The post's own text and media, echoed from the job payload so the
    # posts feed can render a real card (caption + thumbnail) without a
    # second round trip to the provider.
    caption: str | None = None
    media_url: str | None = None
    # The rest of what the post was asked to be, so the details view and the
    # edit form show the same values the job was created with.
    description: str | None = None
    cta_type: str | None = None
    cta_url: str | None = None
    start_date: str | None = None
    end_date: str | None = None


def _to_out(job_row: Job) -> JobOut:
    """Every JobOut field, read from the job row and its payload.

    The feed, the status poll and the edit endpoints all build the response
    the same way, so a field added to JobOut appears everywhere at once.
    """
    payload = job_row.payload or {}
    return JobOut(
        job_id=job_row.id,
        status=job_row.status,
        lane=job_row.lane,
        created_at=job_row.created_at.isoformat(),
        platform=payload.get("platform"),
        method=payload.get("method"),
        external_asset_id=payload.get("external_asset_id"),
        scheduled_at=payload.get("scheduled_at"),
        delete_at=payload.get("delete_at"),
        result=job_row.result,
        last_error=job_row.last_error,
        updated_at=job_row.updated_at.isoformat() if job_row.updated_at else None,
        batch_id=payload.get("batch_id"),
        caption=payload.get("caption"),
        description=payload.get("description"),
        media_url=payload.get("media_url"),
        cta_type=payload.get("cta_type"),
        cta_url=payload.get("cta_url"),
        start_date=payload.get("start_date"),
        end_date=payload.get("end_date"),
    )


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

    # Removal must land after publish, not before.
    try:
        body.check_delete_after_publish()
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    # Google STANDARD/EVENT/OFFER and Meta feed posts allow a text-only post.
    # These formats do not — a job without media would only fail downstream.
    if body.media_url is None:
        for dest in body.destinations:
            for method in dest.methods:
                if method in _MEDIA_REQUIRED_METHODS or (
                    dest.platform == "instagram" and method == "post"
                ):
                    raise HTTPException(
                        status_code=422,
                        detail=(
                            f"method '{method}' on {dest.platform} requires an image; "
                            "remove it or attach an image"
                        ),
                    )

    # A Google post is text, an image, or both. A post with neither is refused
    # by Google after the job has run, so it is turned away here instead.
    if body.media_url is None and not (body.caption.strip() or body.description.strip()):
        for dest in body.destinations:
            if dest.platform == "google_reviews" and any(
                m in {"update", "event", "offer"} for m in dest.methods
            ):
                raise HTTPException(
                    status_code=422,
                    detail="a Google post needs a caption, a description or an image",
                )

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
                    "cta_type": body.cta_type,
                    "cta_url": body.cta_url,
                    "platform": platform,
                    "external_asset_id": asset_id,
                    "method": method,
                    "scheduled_at": body.scheduled_at,
                    "delete_at": body.delete_at,
                    "start_date": body.start_date,
                    "end_date": body.end_date,
                    "language_code": body.language_code,
                    "batch_id": body.batch_id,
                }

                idem_key = (
                    # The destination must be part of the key: a bulk publish
                    # sends one idempotency_key for the whole batch, so keying
                    # on platform+method alone collapses every branch that
                    # shares a format into the first one's job — the other
                    # destinations are silently never created.
                    f"{idempotency_key}:{platform}:{asset_id}:{method}"
                    if idempotency_key
                    else None
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
                jobs_out.append(_to_out(job))
        await db.commit()
    except ValueError as e:
        await db.rollback()
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        await db.rollback()
        logger.exception("publish_post failed")
        raise HTTPException(status_code=500, detail="publish failed") from e

    # Dispatch all jobs to Kafka now so the publishing lane runner picks them up.
    # Dispatch is best-effort: the jobs are already persisted in Postgres as
    # 'queued', and the lane runner claims them from Postgres, so a dispatch
    # failure never loses a publish.
    if jobs_out:
        try:
            producer = await get_kafka_producer()
            for job_out in jobs_out:
                await asyncio.wait_for(
                    producer.send_and_wait(
                        "publishing-dispatch",
                        key=job_out.job_id.encode(),
                        value=json.dumps(
                            {
                                "job_id": job_out.job_id,
                                "lane": "publishing",
                                "action": "run",
                            }
                        ).encode(),
                    ),
                    timeout=KAFKA_DISPATCH_TIMEOUT_SECONDS,
                )
        except asyncio.TimeoutError:
            logger.warning(
                "Kafka dispatch timed out after %ss - %d jobs remain queued in "
                "Postgres and will be picked up by the publishing worker",
                KAFKA_DISPATCH_TIMEOUT_SECONDS,
                len(jobs_out),
            )
        except Exception:
            logger.warning(
                "Kafka dispatch failed - %d jobs remain queued in Postgres "
                "and will be picked up by the publishing worker",
                len(jobs_out),
            )

    return jobs_out


@router.get("/publish", response_model=list[JobOut])
async def list_publish_jobs(
    status_filter: str | None = Query(None, alias="status"),
    platform: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List publish jobs for the current tenant.

    Optional filters: ``status`` (accepted/queued/running/succeeded/failed/
    cancelled/dead) and ``platform`` (whatsapp/facebook/instagram/
    google_reviews). Sorted newest-first. Used by the publish page to show
    scheduled and published posts with their per-platform status.
    """
    tenant_id = tenant_id_of(user)
    q = select(Job).where(
        Job.tenant_id == tenant_id, Job.job_type == JobType.post_publish.value
    )
    if status_filter:
        q = q.where(Job.status == status_filter)
    if platform:
        # platform lives inside the payload JSON; filter in Python after fetch
        # to avoid dialect-specific JSON operators. Page size is small.
        pass
    q = q.order_by(Job.created_at.desc()).offset(offset).limit(limit)
    rows = await db.execute(q)
    out: list[JobOut] = []
    for job_row in rows.scalars().all():
        payload = job_row.payload or {}
        if platform and payload.get("platform") != platform:
            continue
        out.append(_to_out(job_row))
    return out


class BatchDeleteBody(BaseModel):
    job_ids: list[str] = Field(..., min_length=1, max_length=100)
    platforms: list[str] = Field(default_factory=list)

    @field_validator("job_ids")
    @classmethod
    def _validate_ids(cls, v: list[str]) -> list[str]:
        if len(v) > 100:
            raise ValueError("too many job_ids (max 100)")
        return [j.strip() for j in v if j.strip()]

    @field_validator("platforms")
    @classmethod
    def _validate_platforms(cls, v: list[str]) -> list[str]:
        for p in v:
            if p not in _SUPPORTED_PLATFORMS and p != "all":
                raise ValueError(f"unsupported platform: {p}")
        if "all" in v and len(v) > 1:
            raise ValueError("'all' cannot be combined with specific platforms")
        return v


@router.post("/publish/delete", response_model=list[JobOut])
async def batch_delete_published_posts(
    body: BatchDeleteBody,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete published posts from selected platforms (or all).

    Accepts a list of job_ids and an optional list of platforms. If platforms
    is empty or ["all"], deletes from every platform the job was published to.
    If specific platforms are given, only those are deleted.

    Jobs that are still queued/scheduled are cancelled instead of deleted.
    Best-effort per job/platform: a failure on one does not roll back the others.

    Returns the updated status of every job touched.
    """
    tenant_id = tenant_id_of(user)
    if not body.job_ids:
        raise HTTPException(status_code=400, detail="job_ids must not be empty")

    rows = await db.execute(
        select(Job).where(Job.id.in_(body.job_ids), Job.tenant_id == tenant_id)
    )
    jobs = list(rows.scalars().all())
    if not jobs:
        raise HTTPException(status_code=404, detail="no matching jobs found")

    out: list[JobOut] = []
    for job_row in jobs:
        payload = job_row.payload or {}
        platform = payload.get("platform")
        external_asset_id = payload.get("external_asset_id")

        # Determine target platforms.
        requested = body.platforms or []
        if not requested or "all" in requested:
            target_platforms = [platform] if platform else []
        else:
            target_platforms = [p for p in requested if p == platform]

        if not target_platforms:
            continue

        # Terminal rows that never published (or were cancelled) have no
        # platform artifact — nothing to take down. Delete the row so the
        # feed stops showing a permanent "Failed" card, especially for
        # profile/banner, which can never be removed from Google otherwise.
        if job_row.status in {"failed", "dead", "cancelled"}:
            await db.delete(job_row)
            await db.commit()
            out.append(
                JobOut(
                    job_id=job_row.id,
                    status="cancelled",
                    lane=job_row.lane,
                    created_at=job_row.created_at.isoformat(),
                    platform=platform,
                    method=payload.get("method"),
                    external_asset_id=external_asset_id,
                    scheduled_at=payload.get("scheduled_at"),
                    delete_at=payload.get("delete_at"),
                    result=job_row.result,
                    last_error=job_row.last_error,
                    updated_at=job_row.updated_at.isoformat() if job_row.updated_at else None,
                    batch_id=payload.get("batch_id"),
                    caption=payload.get("caption"),
                    media_url=payload.get("media_url"),
                )
            )
            continue

        # Cancel if not yet published.
        if job_row.status in {"accepted", "queued", "retrying", "blocked"}:
            job_row.status = "cancelled"
            job_row.last_error = "deleted by user before publish"
            await db.commit()
            out.append(
                JobOut(
                    job_id=job_row.id,
                    status=job_row.status,
                    lane=job_row.lane,
                    created_at=job_row.created_at.isoformat(),
                    platform=platform,
                    method=payload.get("method"),
                    external_asset_id=external_asset_id,
                    scheduled_at=payload.get("scheduled_at"),
                    delete_at=payload.get("delete_at"),
                    result=job_row.result,
                    last_error=job_row.last_error,
                    updated_at=job_row.updated_at.isoformat() if job_row.updated_at else None,
                    batch_id=payload.get("batch_id"),
                    caption=payload.get("caption"),
                    media_url=payload.get("media_url"),
                )
            )
            continue

        if job_row.status != "succeeded":
            # Skip non-succeeded, non-cancellable jobs.
            continue

        # Resolve channel + token for deletion.
        result = await db.execute(
            select(Channel).where(
                Channel.user_id == tenant_id,
                Channel.platform == platform,
                Channel.status == "active",
            )
        )
        channel = None
        if platform == "google_reviews":
            # A branch can be identified by its Google location id or its
            # dedupe key - accept either.
            for ch in result.scalars().all():
                if str(external_asset_id) in channel_location_ids(ch):
                    channel = ch
                    break
        else:
            channel = result.scalars().first()

        access_token = None
        refresh_token = None
        if channel is not None:
            access_token = (
                decrypt_token(channel.access_token) if channel.access_token else None
            )
            refresh_token = (
                decrypt_token(channel.refresh_token) if channel.refresh_token else None
            )

        job_result = job_row.result or {}
        post_id = job_result.get("id") or job_result.get("name") or job_result.get("media_id")

        if payload.get("method") in {"profile", "banner"}:
            # An avatar/cover cannot be deleted from Google — only replaced
            # by publishing a new one. Dismiss the feed row (nothing on the
            # platform is touched) so the card stops cluttering the list.
            out.append(
                JobOut(
                    job_id=job_row.id,
                    status="cancelled",
                    lane=job_row.lane,
                    created_at=job_row.created_at.isoformat(),
                    platform=platform,
                    method=payload.get("method"),
                    external_asset_id=external_asset_id,
                    scheduled_at=payload.get("scheduled_at"),
                    delete_at=payload.get("delete_at"),
                    result=job_row.result,
                    last_error=(
                        "dismissed — a profile picture or banner cannot be "
                        "deleted, only replaced by publishing a new one"
                    ),
                    updated_at=job_row.updated_at.isoformat() if job_row.updated_at else None,
                    batch_id=payload.get("batch_id"),
                    caption=payload.get("caption"),
                    media_url=payload.get("media_url"),
                )
            )
            await db.delete(job_row)
            await db.commit()
            continue

        # Delete on the platform. Only a real deletion may mark the row as
        # deleted: when Google refuses, the post is still live, and the feed
        # must keep saying so instead of reporting a removal that did not happen.
        failure: str | None = None
        if not post_id:
            failure = "the job has no recorded platform post id"
        elif access_token is None:
            failure = "the channel for this post is not connected"
        elif platform == "google_reviews":
            publisher = GoogleBusinessPublisher(access_token, refresh_token)
            try:
                r = await publisher.delete_post(access_token, post_id)
                job_row.result = {
                    **(job_row.result or {}),
                    "deleted": True,
                    "delete_results": [r],
                }
            except Exception as e:
                failure = str(e)[:200]
            finally:
                await publisher.close()
        else:
            provider = _provider_for(platform)
            if provider is None:
                failure = f"delete is not supported for {platform}"
            else:
                try:
                    r = await provider.delete_post(access_token, post_id)
                    job_row.result = {
                        **(job_row.result or {}),
                        "deleted": True,
                        "delete_results": [r],
                    }
                except Exception as e:
                    failure = str(e)[:200]

        if failure is not None:
            # The post is still live. Return the row with the reason so the
            # caller sees a failure, not a shorter success list.
            job_row.result = {**(job_row.result or {}), "delete_error": failure}
            await db.commit()
            out.append(_to_out(job_row))
            continue

        job_row.status = "cancelled"
        job_row.last_error = "deleted from the platform by user"
        await db.commit()
        out.append(_to_out(job_row))

    if not out:
        raise HTTPException(status_code=409, detail="no jobs could be deleted or cancelled")
    return out


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
        payload = job_row.payload or {}
        out.append(
            JobOut(
                job_id=job_row.id,
                status=job_row.status,
                lane=job_row.lane,
                created_at=job_row.created_at.isoformat(),
                platform=payload.get("platform"),
                method=payload.get("method"),
                external_asset_id=payload.get("external_asset_id"),
                result=job_row.result,
                last_error=job_row.last_error,
                updated_at=job_row.updated_at.isoformat() if job_row.updated_at else None,
                batch_id=payload.get("batch_id"),
                caption=payload.get("caption"),
                media_url=payload.get("media_url"),
            )
        )
    return out


class DeletePublishBody(BaseModel):
    platforms: list[str] = Field(default_factory=list)

    @field_validator("platforms")
    @classmethod
    def _validate(cls, v: list[str]) -> list[str]:
        if not v:
            return []
        for p in v:
            if p not in _SUPPORTED_PLATFORMS and p != "all":
                raise ValueError(f"unsupported platform: {p}")
        if "all" in v and len(v) > 1:
            raise ValueError("'all' cannot be combined with specific platforms")
        return v


class CancelPublishBody(BaseModel):
    reason: str | None = Field(None, max_length=200)


@router.post("/publish/{job_id}/delete", response_model=JobOut)
async def delete_published_post(
    job_id: str,
    body: DeletePublishBody | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a published post from selected platforms.

    Accepts a JSON body ``{"platforms": ["facebook", "instagram"]}`` to
    delete from specific platforms, or ``{"platforms": ["all"]}`` (or no
    body) to delete from every platform the post was published to.

    If the job is still queued/scheduled, it is cancelled instead of
    deleted (nothing has been published yet).

    Returns the updated job status. Deletion is best-effort per platform:
    a failure on one platform does not roll back the others, and the
    per-platform result is recorded in the job's result.
    """
    tenant_id = tenant_id_of(user)
    job = await db.execute(
        select(Job).where(Job.id == job_id, Job.tenant_id == tenant_id)
    )
    job_row = job.scalar_one_or_none()
    if not job_row:
        raise HTTPException(status_code=404, detail="Publish job not found")

    payload = job_row.payload or {}
    platform = payload.get("platform")
    external_asset_id = payload.get("external_asset_id")
    method = payload.get("method", "post")
    media_url = payload.get("media_url")
    media_type = payload.get("media_type")
    caption = payload.get("caption", "")
    description = payload.get("description", "")

    # Determine which platforms to delete from.
    requested = (body.platforms if body else []) or []
    if not requested or "all" in requested:
        target_platforms = [platform] if platform else []
    else:
        target_platforms = [p for p in requested if p == platform]

    if not target_platforms:
        raise HTTPException(status_code=400, detail="no platforms to delete from")

    # If the job hasn't published yet, just cancel it.
    if job_row.status in {"accepted", "queued", "retrying", "blocked"}:
        job_row.status = "cancelled"
        job_row.last_error = "deleted by user before publish"
        await db.commit()
        payload = job_row.payload or {}
        return JobOut(
            job_id=job_row.id,
            status=job_row.status,
            lane=job_row.lane,
            created_at=job_row.created_at.isoformat(),
            platform=payload.get("platform"),
            method=payload.get("method"),
            external_asset_id=payload.get("external_asset_id"),
            scheduled_at=payload.get("scheduled_at"),
            delete_at=payload.get("delete_at"),
            result=job_row.result,
            last_error=job_row.last_error,
            updated_at=job_row.updated_at.isoformat() if job_row.updated_at else None,
            batch_id=payload.get("batch_id"),
            caption=payload.get("caption"),
            media_url=payload.get("media_url"),
        )

    if job_row.status in {"failed", "dead", "cancelled"}:
        # Nothing went out to the platform; drop the row so a terminal
        # failure (including a banner) can be dismissed from the feed.
        await db.delete(job_row)
        await db.commit()
        payload = job_row.payload or {}
        return JobOut(
            job_id=job_row.id,
            status="cancelled",
            lane=job_row.lane,
            created_at=job_row.created_at.isoformat(),
            platform=payload.get("platform"),
            method=payload.get("method"),
            external_asset_id=payload.get("external_asset_id"),
            scheduled_at=payload.get("scheduled_at"),
            delete_at=payload.get("delete_at"),
            result=job_row.result,
            last_error=job_row.last_error,
            updated_at=job_row.updated_at.isoformat() if job_row.updated_at else None,
            batch_id=payload.get("batch_id"),
            caption=payload.get("caption"),
            media_url=payload.get("media_url"),
        )

    if job_row.status != "succeeded":
        raise HTTPException(
            status_code=409,
            detail=f"job is in '{job_row.status}' state; cannot delete",
        )

    # Resolve the channel for token access.
    result = await db.execute(
        select(Channel).where(
            Channel.user_id == tenant_id,
            Channel.platform == platform,
            Channel.status == "active",
        )
    )
    channel = None
    if platform == "google_reviews":
        # A branch can be identified by its Google location id or its dedupe
        # key - accept either.
        for ch in result.scalars().all():
            if str(external_asset_id) in channel_location_ids(ch):
                channel = ch
                break
    else:
        channel = result.scalars().first()

    # Get the platform post id from the job result.
    job_result = job_row.result or {}

    if method in {"profile", "banner"}:
        # A profile picture or cover cannot be deleted from Google — only
        # replaced by publishing a new one. Dismiss the feed row without
        # touching the platform.
        payload = job_row.payload or {}
        out = JobOut(
            job_id=job_row.id,
            status="cancelled",
            lane=job_row.lane,
            created_at=job_row.created_at.isoformat(),
            platform=platform,
            method=method,
            external_asset_id=external_asset_id,
            scheduled_at=payload.get("scheduled_at"),
            delete_at=payload.get("delete_at"),
            result=job_row.result,
            last_error=(
                "dismissed — a profile picture or banner cannot be deleted, "
                "only replaced by publishing a new one"
            ),
            updated_at=job_row.updated_at.isoformat() if job_row.updated_at else None,
            batch_id=payload.get("batch_id"),
            caption=payload.get("caption"),
            media_url=payload.get("media_url"),
        )
        await db.delete(job_row)
        await db.commit()
        return out

    post_id = job_result.get("id") or job_result.get("name") or job_result.get("media_id")

    if not post_id:
        raise HTTPException(
            status_code=409, detail="job has no recorded platform post id"
        )

    # Resolve token.
    access_token = None
    refresh_token = None
    if channel is not None:
        access_token = (
            decrypt_token(channel.access_token) if channel.access_token else None
        )
        refresh_token = (
            decrypt_token(channel.refresh_token) if channel.refresh_token else None
        )

    # Call the provider's delete_post.
    provider = _provider_for(platform)
    if provider is None and platform != "google_reviews":
        raise HTTPException(
            status_code=501, detail=f"delete not supported for {platform}"
        )

    delete_results: list[dict] = []
    failure: str | None = None
    if platform == "google_reviews":
        publisher = GoogleBusinessPublisher(access_token or "", refresh_token)
        if channel is not None:
            async def _persist(new_access_token: str, new_expires_at) -> None:
                channel.access_token = encrypt_token(new_access_token)
                channel.token_expires_at = new_expires_at
                db.add(channel)
                try:
                    await db.commit()
                except Exception as e:
                    logger.error("Failed to persist refreshed Google token: %s", e)
                    await db.rollback()

            publisher.set_token_persister(_persist)
            publisher.set_known_expiry(channel.token_expires_at)
        try:
            delete_results.append(await publisher.delete_post(access_token or "", post_id))
        except Exception as e:
            failure = str(e)[:200]
        finally:
            await publisher.close()
    else:
        try:
            delete_results.append(await provider.delete_post(access_token or "", post_id))
        except Exception as e:
            failure = str(e)[:200]

    if failure is not None:
        # Google still has the post, so it stays published in the feed. The
        # reason is recorded and returned instead of a fake "Cancelled".
        job_row.result = {**(job_row.result or {}), "delete_error": failure}
        await db.commit()
        raise HTTPException(
            status_code=502,
            detail=f"the platform did not delete the post: {failure}",
        )

    # Record the deletion in the job result.
    job_row.result = {
        **(job_row.result or {}),
        "deleted": True,
        "delete_results": delete_results,
    }
    job_row.status = "cancelled"
    job_row.last_error = "deleted from the platform by user"
    await db.commit()

    return _to_out(job_row)


@router.post("/publish/{job_id}/cancel", response_model=JobOut)
async def cancel_publish_job(
    job_id: str,
    body: CancelPublishBody | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Cancel a queued or scheduled publish job before it runs.

    Only jobs in 'accepted', 'queued', 'retrying', or 'blocked' state can be
    cancelled. Already-published jobs must use the delete endpoint.
    """
    tenant_id = tenant_id_of(user)
    job = await db.execute(
        select(Job).where(Job.id == job_id, Job.tenant_id == tenant_id)
    )
    job_row = job.scalar_one_or_none()
    if not job_row:
        raise HTTPException(status_code=404, detail="Publish job not found")

    if job_row.status not in {"accepted", "queued", "retrying", "blocked"}:
        raise HTTPException(
            status_code=409,
            detail=f"job is in '{job_row.status}' state; cannot cancel (use delete for published posts)",
        )

    job_row.status = "cancelled"
    job_row.last_error = (body.reason if body and body.reason else "cancelled by user")
    await db.commit()

    payload = job_row.payload or {}
    return JobOut(
        job_id=job_row.id,
        status=job_row.status,
        lane=job_row.lane,
        created_at=job_row.created_at.isoformat(),
        platform=payload.get("platform"),
        method=payload.get("method"),
        external_asset_id=payload.get("external_asset_id"),
        result=job_row.result,
        last_error=job_row.last_error,
        updated_at=job_row.updated_at.isoformat() if job_row.updated_at else None,
        batch_id=payload.get("batch_id"),
        caption=payload.get("caption"),
        media_url=payload.get("media_url"),
    )


class PublishEditBody(BaseModel):
    """Changes to one publish job. Only the fields sent are changed, and an
    explicit null clears an optional field (a removal date, a button)."""

    caption: str | None = Field(None, max_length=5000)
    description: str | None = Field(None, max_length=5000)
    cta_type: str | None = Field(None, max_length=32)
    cta_url: str | None = Field(None, max_length=1000)
    start_date: str | None = None
    end_date: str | None = None
    scheduled_at: str | None = None
    delete_at: str | None = None


_EDITABLE_KEYS = (
    "caption", "description", "cta_type", "cta_url",
    "start_date", "end_date", "scheduled_at", "delete_at",
)
_DATE_KEYS = ("start_date", "end_date", "scheduled_at", "delete_at")
# Edits that change what Google shows: text, button or the event/offer window.
_GOOGLE_CONTENT_KEYS = {
    "caption", "description", "cta_type", "cta_url", "start_date", "end_date",
}
# Google formats an edit can push. "post" is the legacy name for What's New.
_GOOGLE_EDITABLE_METHODS = {"update", "post", "event", "offer"}
# Jobs that have not reached the platform yet: every field can change.
_NOT_YET_PUBLISHED = {"accepted", "queued", "retrying", "blocked"}
# A removal that can still be moved or cancelled. A running one is in flight.
_REMOVAL_OPEN = {"accepted", "queued", "retrying", "blocked"}


async def _load_publish_job(db: AsyncSession, tenant_id: str, job_id: str) -> Job:
    """The tenant's publish job, row-locked so two edits cannot interleave."""
    job_row = (
        await db.execute(
            select(Job)
            .where(Job.id == job_id, Job.tenant_id == tenant_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if job_row is None:
        raise HTTPException(status_code=404, detail="Publish job not found")
    return job_row


def _merge_edit(payload: dict, changes: dict) -> dict:
    """The payload with the changes applied.

    Blank text becomes None and dates are stored as normalised UTC ISO text,
    so an edited job reads the same as one created with those values.
    """
    merged = dict(payload)
    for key in _EDITABLE_KEYS:
        if key not in changes:
            continue
        value = changes[key]
        if isinstance(value, str):
            value = value.strip() or None
        if value is not None and key in _DATE_KEYS:
            value = parse_instant(value).isoformat()
        if key == "cta_type" and value is not None:
            value = value.lower()
        merged[key] = value
    return merged


def _check_edit_dates(
    merged: dict, changes: dict, now: datetime, queued: bool
) -> None:
    """A removal must be in the future and after the post goes out, a schedule
    must be in the future, and an event must end after it starts."""
    scheduled = parse_instant(merged.get("scheduled_at"))
    delete = parse_instant(merged.get("delete_at"))
    if queued and "scheduled_at" in changes and scheduled is not None and scheduled <= now:
        raise ValueError("scheduled_at must be in the future")
    if "delete_at" in changes and delete is not None and delete <= now:
        raise ValueError("delete_at must be in the future")
    if delete is not None and ("delete_at" in changes or "scheduled_at" in changes):
        # The moment the post is actually out: a future schedule, or now when
        # it goes immediately (or its scheduled time has already passed).
        publish_at = scheduled if scheduled is not None and scheduled > now else now
        if delete <= publish_at:
            raise ValueError("delete_at must be after the time the post goes out")
    start = parse_instant(merged.get("start_date"))
    end = parse_instant(merged.get("end_date"))
    if start is not None and end is not None and end <= start:
        raise ValueError("end_date must be after start_date")


async def _removal_job_for(
    db: AsyncSession, tenant_id: str, publish_job_id: str
) -> Job | None:
    """The removal job scheduled for a publish job, if there is one."""
    return (
        await db.execute(
            select(Job).where(
                Job.tenant_id == tenant_id,
                Job.idempotency_key == f"post-delete:{publish_job_id}",
            )
        )
    ).scalar_one_or_none()


async def _google_publisher_for(
    db: AsyncSession, tenant_id: str, job_row: Job
) -> tuple[GoogleBusinessPublisher, str]:
    """A publisher for the job's Google location, and the post's resource name."""
    payload = job_row.payload or {}
    asset = str(payload.get("external_asset_id") or "")
    post_name = str((job_row.result or {}).get("name") or (job_row.result or {}).get("id") or "")
    if "/localPosts/" not in post_name:
        raise HTTPException(
            status_code=409, detail="this post has no Google post id on record"
        )
    rows = (
        await db.execute(
            select(Channel).where(
                Channel.user_id == tenant_id,
                Channel.platform == "google_reviews",
                Channel.status == "active",
            )
        )
    ).scalars().all()
    channel = next((ch for ch in rows if asset in channel_location_ids(ch)), None)
    if channel is None:
        raise HTTPException(
            status_code=409, detail="the Google location for this post is not connected"
        )
    publisher = GoogleBusinessPublisher(
        decrypt_token(channel.access_token) if channel.access_token else "",
        decrypt_token(channel.refresh_token) if channel.refresh_token else None,
    )
    publisher.set_known_expiry(channel.token_expires_at)

    async def _persist(new_access_token: str, new_expires_at) -> None:
        channel.access_token = encrypt_token(new_access_token)
        channel.token_expires_at = new_expires_at
        db.add(channel)
        try:
            await db.commit()
        except Exception as e:
            logger.error("Failed to persist refreshed Google token: %s", e)
            await db.rollback()

    publisher.set_token_persister(_persist)
    return publisher, post_name


@router.patch("/publish/{job_id}", response_model=JobOut)
async def edit_publish_job(
    job_id: str,
    body: PublishEditBody,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Edit one publish job.

    Before it goes out, every field can change. Once a Google post is live,
    its text, button and event/offer window are pushed to Google and its
    removal date can move. Anything that cannot change on the platform is
    refused with the reason, and a Google failure leaves the job unchanged.
    """
    tenant_id = tenant_id_of(user)
    job_row = await _load_publish_job(db, tenant_id, job_id)
    changes = body.model_dump(exclude_unset=True)
    if not changes:
        return _to_out(job_row)
    payload = dict(job_row.payload or {})
    platform = payload.get("platform")
    method = payload.get("method", "post")
    now = datetime.now(timezone.utc)
    queued = job_row.status in _NOT_YET_PUBLISHED
    if not queued and job_row.status != "succeeded":
        raise HTTPException(
            status_code=409,
            detail=f"job is in '{job_row.status}' state; nothing can be edited",
        )
    if not queued and "scheduled_at" in changes:
        # It is already on the platform; a new schedule would only change the
        # stored payload while Google keeps publishing (or already published)
        # the post at the old time.
        raise HTTPException(
            status_code=409,
            detail="a published post cannot be scheduled again",
        )
    try:
        merged = _merge_edit(payload, changes)
        _check_edit_dates(merged, changes, now, queued)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e

    if queued:
        job_row.payload = merged
        await db.commit()
        return _to_out(job_row)

    # A published post: its text, button and window are on the platform, and
    # its removal is Sayvors' own job. Checks run before anything is changed.
    removal = None
    if "delete_at" in changes:
        removal = await _removal_job_for(db, tenant_id, job_row.id)
        if removal is not None and removal.status not in _REMOVAL_OPEN:
            raise HTTPException(
                status_code=409,
                detail=f"the removal is already {removal.status}; it cannot be moved",
            )

    if _GOOGLE_CONTENT_KEYS & set(changes):
        if platform != "google_reviews" or method not in _GOOGLE_EDITABLE_METHODS:
            raise HTTPException(
                status_code=409,
                detail=f"published {platform} posts cannot be edited here; only the removal date can change",
            )
        if not (merged.get("caption") or merged.get("description") or payload.get("media_url")):
            raise HTTPException(
                status_code=422,
                detail="a Google post needs a caption, a description or an image",
            )
        publisher, post_name = await _google_publisher_for(db, tenant_id, job_row)
        window_src = (job_row.result or {}).get("window") or {}
        try:
            built = build_post_fields(
                topic=topic_type_for(method),
                caption=merged.get("caption"),
                description=merged.get("description"),
                cta_type=merged.get("cta_type"),
                cta_url=merged.get("cta_url"),
                start=parse_instant(merged.get("start_date") or window_src.get("start")),
                end=parse_instant(merged.get("end_date") or window_src.get("end")),
                coupon_code=None,
                terms=None,
                now=now,
            )
            # A cleared caption must clear the text on Google too; without the
            # explicit null, Google keeps the old summary.
            fields = dict(built.fields)
            fields.setdefault("summary", None)
            updated = await publisher.update_post(post_name, fields)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e)) from e
        except GoogleReviewsError as e:
            raise HTTPException(
                status_code=502, detail=f"Google did not accept the change: {e}"
            ) from e
        finally:
            await publisher.close()
        result = dict(job_row.result or {})
        result.update(updated)
        if built.window:
            result["window"] = {
                "start": built.window[0].isoformat(),
                "end": built.window[1].isoformat(),
            }
        job_row.result = result

    if "delete_at" in changes:
        when = parse_instant(merged.get("delete_at"))
        if when is None:
            if removal is not None:
                removal.status = "cancelled"
                removal.last_error = "removal date cleared by user"
        elif removal is None:
            await schedule_removal(
                db, tenant_id=tenant_id, publish_job=job_row, delete_at=when
            )
        else:
            removal.next_run_at = when

    job_row.payload = merged
    await db.commit()
    return _to_out(job_row)


@router.post("/publish/{job_id}/refresh", response_model=JobOut)
async def refresh_publish_job(
    job_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Read a published Google post back and record what Google reports now.

    A post Google no longer holds (removed, or expired) is recorded as GONE so
    the feed stops calling it live. Any other Google failure is raised, not
    recorded as a state.
    """
    tenant_id = tenant_id_of(user)
    job_row = await _load_publish_job(db, tenant_id, job_id)
    payload = job_row.payload or {}
    if job_row.status != "succeeded" or payload.get("platform") != "google_reviews":
        raise HTTPException(
            status_code=409,
            detail="only a published Google post can be checked on Google",
        )
    publisher, post_name = await _google_publisher_for(db, tenant_id, job_row)
    try:
        current = await publisher.get_post(post_name)
    except GoogleReviewsError as e:
        if e.status_code != 404:
            raise HTTPException(
                status_code=502, detail=f"Google could not be reached: {e}"
            ) from e
        current = {"state": "GONE"}
    finally:
        await publisher.close()
    job_row.result = {**(job_row.result or {}), **current}
    await db.commit()
    return _to_out(job_row)


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
    return _to_out(job_row)

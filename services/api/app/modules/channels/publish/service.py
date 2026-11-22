"""Publish pipeline helpers shared by the HTTP router and the job runner.

Removing a published post is needed in two places: the "Remove" action
an operator clicks, and the scheduled removal of a promotional post when
its date arrives. Both must reach the provider the same way, so the call
lives here and both callers use it — one implementation, one set of
rules about which platforms can be removed from.

The account surfaces (profile picture / banner) are NOT posts: there is
nothing on the platform to delete, only to replace. Callers must skip
them, and `is_removable_method` is the single place that says so.
"""
from __future__ import annotations

import logging
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...jobs.models import Job
from ...jobs.service import submit_job
from ...jobs.types import JobType
from ..meta.providers.facebook import FacebookAdapter
from ..meta.providers.google_publish import GoogleBusinessPublisher
from ..meta.providers.instagram import InstagramAdapter
from ..meta.providers.whatsapp import WhatsAppAdapter
from ..models import Channel
from ..service import channel_location_ids, decrypt_token, encrypt_token

logger = logging.getLogger(__name__)

# Methods that publish into a feed. The account surfaces (profile /
# banner) are excluded — they replace an image on the account and have
# no post to delete.
REMOVABLE_METHODS = {
    "post",
    "story",
    "reel",
    "status",
    "update",
    "event",
    "offer",
}


def is_removable_method(method: str | None) -> bool:
    """Whether this format publishes something that can be taken down."""
    return (method or "post") in REMOVABLE_METHODS


def provider_for(platform: str):
    """Return the provider instance for a platform, or None if unsupported."""
    providers = {
        "whatsapp": WhatsAppAdapter(),
        "facebook": FacebookAdapter(),
        "instagram": InstagramAdapter(),
    }
    return providers.get(platform)


async def resolve_publish_channel(
    db: AsyncSession, tenant_id: str, platform: str, external_asset_id: str
) -> Channel | None:
    """The tenant's active channel for a publish destination, if any.

    Google branches can be identified by their Google location id or their
    dedupe key, so either matches.
    """
    result = await db.execute(
        select(Channel).where(
            Channel.user_id == tenant_id,
            Channel.platform == platform,
            Channel.status == "active",
        )
    )
    if platform == "google_reviews":
        for ch in result.scalars().all():
            if str(external_asset_id) in channel_location_ids(ch):
                return ch
        return None
    return result.scalars().first()


async def delete_published_from_platform(
    *,
    platform: str,
    post_id: str,
    channel: Channel | None,
    db: AsyncSession,
) -> dict:
    """Remove one published post from its platform.

    Raises on a provider failure so the caller decides what to do: the
    HTTP route records the error per platform and carries on with the
    rest, while the scheduled-removal job lets the runner retry — a
    promo that must come down on a date should not be lost to one
    flaky call.
    """
    access_token = (
        decrypt_token(channel.access_token)
        if channel is not None and channel.access_token
        else None
    )
    refresh_token = (
        decrypt_token(channel.refresh_token)
        if channel is not None and channel.refresh_token
        else None
    )

    if platform == "google_reviews":
        publisher = GoogleBusinessPublisher(access_token or "", refresh_token)
        if channel is not None:
            # Google's tokens expire in ~1 hour, so a refreshed token is
            # written back to the channel row.
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
        return await publisher.delete_post(access_token or "", post_id)

    provider = provider_for(platform)
    if provider is None:
        raise ValueError(f"delete not supported for {platform}")
    return await provider.delete_post(access_token or "", post_id)


async def schedule_removal(
    db: AsyncSession,
    *,
    tenant_id: str,
    publish_job: Job,
    delete_at: datetime,
) -> Job:
    """Queue the removal of a published post for a given time.

    The removal is a job of its own so it rides the same lane, lease,
    retry and idempotency machinery as every other piece of work. A post
    that must come down on a date is scheduled work, not a cron entry
    bolted onto the side.

    The removal job points at the publish job rather than copying the
    platform post id: that id only exists once the publish succeeds, and
    reading it from the publish job keeps the two in step.
    """
    return await submit_job(
        db,
        tenant_id=tenant_id,
        job_type=JobType.post_delete.value,
        payload={"publish_job_id": publish_job.id},
        lane="publishing",
        priority=50,
        max_attempts=5,
        idempotency_key=f"post-delete:{publish_job.id}",
        subject_type="post_publish",
        subject_id=publish_job.id,
        lane_key=publish_job.lane_key,
        next_run_at=delete_at,
    )


async def batch_remove_published_posts(
    db: AsyncSession,
    *,
    tenant_id: str,
    job_ids: list[str],
    platforms: list[str] | None = None,
) -> list[dict]:
    """Remove/cancel/dismiss publish jobs now. Returns JobOut-like dicts.

    Mirrors the /publish/delete endpoint behavior so UI and background jobs
    share one implementation.
    """
    from ...jobs.models import Job
    from ..models import Channel
    from ..service import channel_location_ids, decrypt_token

    requested_platforms = platforms or []
    rows = await db.execute(select(Job).where(Job.id.in_(job_ids), Job.tenant_id == tenant_id))
    jobs = list(rows.scalars().all())
    if not jobs:
        return []

    out: list[dict] = []
    for job_row in jobs:
        payload = job_row.payload or {}
        platform = payload.get("platform")
        external_asset_id = payload.get("external_asset_id")

        if not requested_platforms or "all" in requested_platforms:
            target_platforms = [platform] if platform else []
        else:
            target_platforms = [p for p in requested_platforms if p == platform]
        if not target_platforms:
            continue

        base = {
            "job_id": job_row.id,
            "status": job_row.status,
            "lane": job_row.lane,
            "created_at": job_row.created_at.isoformat(),
            "platform": platform,
            "method": payload.get("method"),
            "external_asset_id": external_asset_id,
            "scheduled_at": payload.get("scheduled_at"),
            "delete_at": payload.get("delete_at"),
            "result": job_row.result,
            "last_error": job_row.last_error,
            "updated_at": job_row.updated_at.isoformat() if job_row.updated_at else None,
            "batch_id": payload.get("batch_id"),
            "caption": payload.get("caption"),
            "media_url": payload.get("media_url"),
        }

        if job_row.status in {"failed", "dead", "cancelled"}:
            await db.delete(job_row)
            await db.commit()
            base["status"] = "cancelled"
            out.append(base)
            continue

        if job_row.status in {"accepted", "queued", "retrying", "blocked"}:
            job_row.status = "cancelled"
            job_row.last_error = "deleted by user before publish"
            await db.commit()
            base["status"] = job_row.status
            base["last_error"] = job_row.last_error
            base["updated_at"] = job_row.updated_at.isoformat() if job_row.updated_at else None
            out.append(base)
            continue

        if job_row.status != "succeeded":
            continue

        if payload.get("method") in {"profile", "banner"}:
            base["status"] = "cancelled"
            base["last_error"] = (
                "dismissed — a profile picture or banner cannot be deleted, only replaced by publishing a new one"
            )
            await db.delete(job_row)
            await db.commit()
            out.append(base)
            continue

        result = await db.execute(
            select(Channel).where(
                Channel.user_id == tenant_id,
                Channel.platform == platform,
                Channel.status == "active",
            )
        )
        channel = None
        if platform == "google_reviews":
            for ch in result.scalars().all():
                if str(external_asset_id) in channel_location_ids(ch):
                    channel = ch
                    break
        else:
            channel = result.scalars().first()

        job_result = job_row.result or {}
        post_id = job_result.get("id") or job_result.get("name") or job_result.get("media_id")
        failure: str | None = None
        if not post_id:
            failure = "the job has no recorded platform post id"
        elif channel is None or (not channel.access_token and not channel.refresh_token):
            failure = "the channel for this post is not connected"
        else:
            try:
                r = await delete_published_from_platform(
                    platform=platform,
                    post_id=str(post_id),
                    channel=channel,
                    db=db,
                )
                job_row.result = {**(job_row.result or {}), "deleted": True, "delete_results": [r]}
            except Exception as e:
                failure = str(e)[:200]

        if failure is not None:
            job_row.result = {**(job_row.result or {}), "delete_error": failure}
            await db.commit()
            base["result"] = job_row.result
            base["updated_at"] = job_row.updated_at.isoformat() if job_row.updated_at else None
            out.append(base)
            continue

        job_row.status = "cancelled"
        job_row.last_error = "deleted from the platform by user"
        await db.commit()
        base["status"] = job_row.status
        base["last_error"] = job_row.last_error
        base["result"] = job_row.result
        base["updated_at"] = job_row.updated_at.isoformat() if job_row.updated_at else None
        out.append(base)

    return out

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

    Google branches can be identified by their Localith listing id, their
    Google location id, or both — so any of them match.
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

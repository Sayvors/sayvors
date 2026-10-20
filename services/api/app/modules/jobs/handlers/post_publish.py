"""post.publish job handler — publishes one post to one destination+format.

Idempotent by job id: the same job never publishes twice because the lane
runner checks terminal status before running, and each destination+format
gets its own job row with a unique lane_key (the Kafka partition key).
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...channels.meta.providers.whatsapp import WhatsAppAdapter
from ...channels.meta.providers.instagram import InstagramAdapter
from ...channels.meta.providers.facebook import FacebookAdapter
from ...channels.meta.providers.google_publish import GoogleBusinessPublisher
from ...channels.google_reviews import GoogleReviewsError
from ...channels.models import Channel
from ...channels.service import decrypt_token, encrypt_token
from ..models import Job
from ..service import complete_job

logger = logging.getLogger(__name__)

_SUPPORTED_PLATFORMS = {"whatsapp", "facebook", "instagram", "google_reviews"}


async def handle_post_publish(job: Job, db: AsyncSession) -> dict | None:
    """Publish one post to one destination+format.

    Payload contract:
        {
            "media_key": str,          # storage key from /storage/upload
            "media_url": str,          # public URL the provider fetches
            "media_type": "image"|"video",
            "caption": str,
            "description": str,
            "platform": str,           # whatsapp|facebook|instagram|x|...
            "external_asset_id": str,  # the Meta page/IG account/Wa number id
            "method": "post"|"story"|"reel"|"status",
            "scheduled_at": str|null,  # ISO datetime or null
        }
    Returns a result dict persisted on Job.result.
    """
    payload = job.payload or {}
    media_url = payload.get("media_url")
    media_type = payload.get("media_type")
    caption = payload.get("caption", "")
    description = payload.get("description", "")
    platform = payload.get("platform")
    external_asset_id = payload.get("external_asset_id")
    method = payload.get("method", "post")
    scheduled_at = payload.get("scheduled_at")

    if not platform:
        raise ValueError("platform missing from payload")
    if not external_asset_id:
        raise ValueError("external_asset_id missing from payload")

    # Resolve the channel row (not just the token) so we can refresh Google
    # tokens and read metadata like the Google location_id.
    channel = await _resolve_channel(db, job.tenant_id, platform, external_asset_id)
    if channel is None:
        raise ValueError(
            f"no active channel for platform={platform} asset={external_asset_id}"
        )

    access_token = decrypt_token(channel.access_token) if channel.access_token else None
    refresh_token = decrypt_token(channel.refresh_token) if channel.refresh_token else None
    if not access_token and not refresh_token:
        raise ValueError(
            f"no credentials stored for platform={platform} asset={external_asset_id}"
        )

    # Google's access tokens expire in ~1 hour, so the publisher gets a
    # persister that writes refreshed tokens back to the channel row.
    if platform == "google_reviews":
        publisher = GoogleBusinessPublisher(access_token or "", refresh_token)
        account_id = channel.platform_user_id
        location_id = external_asset_id
        if account_id and "/" not in account_id:
            account_id = f"accounts/{account_id}"
        if location_id and "/" not in location_id:
            location_id = f"locations/{location_id}"

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

        result = await publisher.publish_post(
            token=access_token or "",
            asset_id=location_id,
            method=method,
            media_url=media_url,
            media_type=media_type,
            caption=caption,
            description=description,
            scheduled_at=scheduled_at,
            account_id=account_id,
        )
    else:
        provider = _provider_for(platform)
        if provider is None:
            raise ValueError(f"no publish provider for platform: {platform}")
        result = await provider.publish_post(
            token=access_token or "",
            asset_id=external_asset_id,
            method=method,
            media_url=media_url,
            media_type=media_type,
            caption=caption,
            description=description,
            scheduled_at=scheduled_at,
        )

    await complete_job(db, job=job, result=result)
    return result


async def _resolve_channel(
    db: AsyncSession, tenant_id: str, platform: str, external_asset_id: str
) -> Channel | None:
    """Resolve the tenant's channel for a publish destination.

    Meta platforms use the asset id as the platform_user_id. Google uses the
    location_id (stored in channel metadata) as the asset id, and the
    account_id as the platform_user_id. Both are tenant-scoped.
    """
    if platform == "google_reviews":
        # location_id lives in metadata_json, not platform_user_id.
        rows = await db.execute(
            select(Channel).where(
                Channel.user_id == tenant_id,
                Channel.platform == "google_reviews",
                Channel.status == "active",
            )
        )
        for ch in rows.scalars().all():
            try:
                import json as _json

                meta = _json.loads(ch.metadata_json or "{}")
            except (ValueError, TypeError):
                meta = {}
            if not isinstance(meta, dict):
                continue
            loc = meta.get("location_id") or meta.get("listing_id")
            if str(loc) == str(external_asset_id):
                return ch
        return None

    result = await db.execute(
        select(Channel).where(
            Channel.user_id == tenant_id,
            Channel.platform_user_id == external_asset_id,
            Channel.platform == platform,
            Channel.status == "active",
        )
    )
    return result.scalar_one_or_none()


def _provider_for(platform: str):
    """Return the provider instance for a platform, or None if unsupported."""
    providers = {
        "whatsapp": WhatsAppAdapter(),
        "facebook": FacebookAdapter(),
        "instagram": InstagramAdapter(),
    }
    return providers.get(platform)

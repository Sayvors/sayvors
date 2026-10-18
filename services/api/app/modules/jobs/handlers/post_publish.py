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
from ...channels.models import Channel
from ..models import Job
from ..service import complete_job

logger = logging.getLogger(__name__)


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

    # Resolve the channel's access token from the DB so the provider can
    # call the Graph API on the tenant's behalf.
    result = await db.execute(
        select(Channel.access_token).where(
            Channel.platform_user_id == external_asset_id,
            Channel.platform == platform,
            Channel.status == "active",
        )
    )
    token_row = result.scalar_one_or_none()
    token = token_row if token_row else None
    if not token:
        raise ValueError(
            f"no active channel token for platform={platform} asset={external_asset_id}"
        )

    provider = _provider_for(platform)
    if provider is None:
        raise ValueError(f"no publish provider for platform: {platform}")

    result = await provider.publish_post(
        token=token,
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


def _provider_for(platform: str):
    """Return the provider instance for a platform, or None if unsupported."""
    providers = {
        "whatsapp": WhatsAppAdapter(),
        "facebook": FacebookAdapter(),
        "instagram": InstagramAdapter(),
    }
    return providers.get(platform)

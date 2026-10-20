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
from ...channels.service import channel_location_ids, decrypt_token, encrypt_token
from ..models import Job
from ..service import complete_job

logger = logging.getLogger(__name__)

_SUPPORTED_PLATFORMS = {"whatsapp", "facebook", "instagram", "google_reviews"}

# Methods that replace an account surface instead of publishing into a
# feed: "profile" swaps the avatar, "banner" swaps the cover image. They
# are delivered by the provider's own asset endpoint, carry no caption,
# and have nothing to delete afterwards.
_ACCOUNT_SURFACE_METHODS = {"profile", "banner"}

# Meta's cap on a WhatsApp business profile photo. Anything larger is
# refused before the upload rather than after a round trip.
PROFILE_IMAGE_MAX_BYTES = 5 * 1024 * 1024


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
            "method": "post"|"story"|"reel"|"status"|"update"|"event"|"offer"
                      |"profile"|"banner",
            "scheduled_at": str|null,  # ISO datetime or null
        }
    Returns a result dict persisted on Job.result.
    """
    payload = job.payload or {}
    media_url = payload.get("media_url")
    media_type = payload.get("media_type")
    media_key = payload.get("media_key")
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

    if method in _ACCOUNT_SURFACE_METHODS:
        result = await _publish_account_surface(
            db=db,
            job=job,
            channel=channel,
            platform=platform,
            external_asset_id=external_asset_id,
            method=method,
            media_url=media_url,
            media_key=media_key,
            media_type=media_type,
            access_token=access_token or "",
            refresh_token=refresh_token,
        )
    elif platform == "google_reviews":
        # Google's access tokens expire in ~1 hour, so the publisher gets a
        # persister that writes refreshed tokens back to the channel row.
        publisher = GoogleBusinessPublisher(access_token or "", refresh_token)
        account_id = channel.platform_user_id
        # The Google API needs the location id in Google's own id space. The
        # destination may have been named by its Localith listing id, so take
        # the location id off the resolved channel, not off the request.
        location_id = _google_location_id(channel) or external_asset_id
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


async def _publish_account_surface(
    *,
    db: AsyncSession,
    job: Job,
    channel: Channel,
    platform: str,
    external_asset_id: str,
    method: str,
    media_url: str | None,
    media_key: str | None,
    media_type: str | None,
    access_token: str,
    refresh_token: str | None,
) -> dict:
    """Replace an account's avatar ("profile") or cover image ("banner").

    These are not feed posts. Each provider exposes its own asset
    endpoint, the caption is ignored, and the result describes the
    changed surface rather than a published post id — so nothing about
    it can be deleted afterwards, only replaced.

    Only the platforms whose API actually exposes the surface are
    accepted. Instagram's IG User node is read-only for these fields, so
    it fails loudly here instead of queueing a doomed job.
    """
    token = access_token
    if not token:
        raise ValueError(f"no access token for platform={platform}")
    if not media_url:
        raise ValueError(f"{method} publishing requires a media URL")
    if media_type and media_type != "image":
        raise ValueError(f"{method} publishing needs an image, not a {media_type}")

    if platform == "google_reviews":
        # Google stores the profile picture and the cover image as
        # location media (PROFILE / COVER categories). The publisher
        # resolves the account and location ids from the channel, the
        # same way the local-post path does.
        account_id = channel.platform_user_id
        if account_id and "/" not in account_id:
            account_id = f"accounts/{account_id}"
        location_id = _google_location_id(channel) or external_asset_id
        if location_id and "/" not in location_id:
            location_id = f"locations/{location_id}"
        publisher = GoogleBusinessPublisher(token, refresh_token)

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

        result = await publisher.set_location_image(
            token=token,
            asset_id=location_id,
            method=method,
            media_url=media_url,
            account_id=account_id,
        )
        return {
            "provider": "google_reviews",
            "method": method,
            "asset_id": external_asset_id,
            **(result or {}),
        }

    if platform == "facebook":
        adapter = FacebookAdapter()
        if method == "profile":
            result = await adapter.set_page_profile_picture(
                external_asset_id, token, url=media_url
            )
        else:
            result = await adapter.set_page_cover_photo(
                external_asset_id, token, url=media_url
            )
        return {
            "provider": "facebook",
            "method": method,
            "asset_id": external_asset_id,
            **(result or {}),
        }

    if platform == "whatsapp" and method == "profile":
        # WhatsApp takes the image as bytes through the resumable upload
        # API (the plain /media id is rejected as profile_picture_handle,
        # #131009), so the image is read back rather than handed over as
        # a URL.
        data, mime = await _read_profile_image(
            job.tenant_id, media_key, media_url
        )
        waba_id = await _whatsapp_waba_id(db, job.tenant_id, external_asset_id)
        await WhatsAppAdapter().set_profile_photo(
            external_asset_id,
            token,
            data,
            mime,
            waba_id=waba_id,
            file_name="profile.png" if mime == "image/png" else "profile.jpg",
        )
        return {
            "provider": "whatsapp",
            "method": method,
            "asset_id": external_asset_id,
            "profile_photo": True,
        }

    raise ValueError(f"{platform} does not support the {method!r} format")


async def _read_profile_image(
    tenant_id: str, media_key: str | None, media_url: str | None
) -> tuple[bytes, str]:
    """Read the image to upload as bytes, with its content type.

    Our own storage is preferred: the key names a file we already hold,
    so there is nothing to fetch. A pasted media link is the fallback,
    and it goes through the SSRF-guarded fetcher (``fetch_pinned_bytes``)
    — never a raw HTTP call — with Meta's cap on a business profile
    photo.
    """
    import asyncio

    from ...core.storage import get_media

    if media_key:
        try:
            data = get_media(tenant_id, media_key)
        except FileNotFoundError as e:
            raise ValueError("the attached image is no longer in storage") from e
    elif media_url:
        from ...core.pinned_http import fetch_pinned_bytes

        # The pinned fetch is sync (httpcore) — run it off the event loop.
        try:
            data = await asyncio.to_thread(
                fetch_pinned_bytes, media_url, max_bytes=PROFILE_IMAGE_MAX_BYTES
            )
        except ValueError as e:
            raise ValueError(f"the attached image could not be read: {e}") from e
    else:
        raise ValueError("this format needs an image to upload")

    if not data:
        raise ValueError("the attached image is empty")
    if len(data) > PROFILE_IMAGE_MAX_BYTES:
        raise ValueError("a profile picture must be under 5 MB")
    return data, _profile_image_content_type(data)


def _profile_image_content_type(data: bytes) -> str:
    """The content type of a profile image, read from its magic bytes.

    Meta's business profile photo accepts JPG and PNG only and rejects a
    mislabelled file outright, so the type is read from the bytes rather
    than from a filename the tenant controls.
    """
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    raise ValueError("a profile picture must be a JPG or PNG image")


async def _whatsapp_waba_id(
    db: AsyncSession, tenant_id: str, phone_number_id: str
) -> str | None:
    """The WABA that owns a phone number, for the resumable upload owner.

    A phone number is discovered under its WABA, so the WABA is the
    parent's external id on the MetaAsset row. Resumable upload sessions
    are created against the owning WABA.
    """
    from ...channels.meta.models import MetaAsset

    rows = await db.execute(
        select(MetaAsset).where(
            MetaAsset.tenant_id == tenant_id,
            MetaAsset.provider == "whatsapp",
            MetaAsset.asset_type == "phone_number",
            MetaAsset.external_asset_id == phone_number_id,
        )
    )
    asset = rows.scalars().first()
    if asset is None or not asset.parent_asset_id:
        return None
    parent = await db.get(MetaAsset, asset.parent_asset_id)
    return parent.external_asset_id if parent else None


def _google_location_id(channel: Channel) -> str | None:
    """The channel's Google location id, in Google's own id space.

    A Localith-mirrored branch is identified by its listing id locally, but
    Google's API only knows the location id, so the location id is read from
    the channel metadata (the listing id is a fallback for channels that
    never carried one).
    """
    try:
        import json as _json

        meta = _json.loads(channel.metadata_json or "{}")
    except (ValueError, TypeError):
        meta = {}
    if isinstance(meta, dict):
        loc = meta.get("location_id")
        if loc:
            return str(loc)
    return str(channel.listing_key) if channel.listing_key else None


async def _resolve_channel(
    db: AsyncSession, tenant_id: str, platform: str, external_asset_id: str
) -> Channel | None:
    """Resolve the tenant's channel for a publish destination.

    Meta platforms use the asset id as the platform_user_id. Google uses the
    location id as the asset id, and the account_id as the platform_user_id.
    Both are tenant-scoped.
    """
    if platform == "google_reviews":
        # The location id lives in metadata_json, not platform_user_id. A
        # Localith-mirrored branch carries a listing_id while a native OAuth
        # channel carries a location_id, and a branch can carry both, so the
        # channel matches on ANY of its ids (metadata location_id, metadata
        # listing_id, the listing_id column).
        rows = await db.execute(
            select(Channel).where(
                Channel.user_id == tenant_id,
                Channel.platform == "google_reviews",
                Channel.status == "active",
            )
        )
        for ch in rows.scalars().all():
            if str(external_asset_id) in channel_location_ids(ch):
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

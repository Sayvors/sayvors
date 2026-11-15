"""Import a connected Google location's posts and gallery media into Sayvors.

On connect we fetch the location profile (name, address, hours, categories,
services) and the reviews (via the connect-import session). This module adds
the rest of the location's public content so it is visible in the dashboard
immediately instead of only after the merchant opens Posts & Media:

  * local posts   -> ``location_posts`` rows (status mirrored from Google)
  * gallery media -> ``location_media`` rows (gallery / cover / profile)

Idempotent: a row is matched by its Google resource name (``google_post_id``)
and updated, never duplicated. Merchant-authored rows (draft/scheduled) are
never overwritten — the import only fills in what Google already shows.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .google_reviews import GoogleReviewsClient, GoogleReviewsError
from .service import decrypt_token, encrypt_token
from ..locations.service import listing_id_of

logger = logging.getLogger(__name__)

# Session factory indirection (same pattern as the billing modules): tests
# swap this for the in-memory test DB.
_session_factory = None


def get_session_factory():
    global _session_factory
    if _session_factory is None:
        from ...database import async_session

        _session_factory = async_session
    return _session_factory


# Google post states -> Sayvors post status.
_POST_STATE_STATUS = {
    "PUBLISHED": "published",
    "PROCESSING": "published",
    "SCHEDULED": "scheduled",
    "REJECTED": "failed",
    "DRAFT": "draft",
}
_POST_TOPIC_TYPE = {"EVENT": "event", "OFFER": "offer", "UPDATE": "update"}

# Google media categories -> Sayvors publish method.
_MEDIA_METHOD = {
    "PROFILE": "profile",
    "COVER": "banner",
    "LOGO": "profile",
}
_MEDIA_TYPE = {"PHOTO": "PHOTO", "VIDEO": "VIDEO"}


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _google_date(value: dict | None) -> datetime | None:
    """Google's {year, month, day} event date -> datetime (UTC noon)."""
    if not isinstance(value, dict):
        return None
    try:
        return datetime(
            int(value["year"]), int(value["month"]), int(value["day"]),
            12, 0, tzinfo=timezone.utc,
        )
    except (KeyError, TypeError, ValueError):
        return None


def _post_status(gp: dict) -> str:
    return _POST_STATE_STATUS.get(str(gp.get("state") or "").upper(), "published")


def _post_type(gp: dict) -> str:
    return _POST_TOPIC_TYPE.get(str(gp.get("topicType") or "").upper(), "update")


def _media_category(m: dict) -> str:
    assoc = m.get("locationAssociation") or {}
    return str(assoc.get("category") or "ADDITIONAL").upper()[:32]


def _media_url(m: dict) -> str:
    return str(m.get("googleUrl") or m.get("sourceUrl") or m.get("thumbnailUrl") or "")


async def import_channel_content(channel_id: str) -> dict:
    """Entry point: open a fresh session and import one channel's content.

    Own session (same pattern as the billing modules) so a content failure
    can never roll back the connect transaction or the review import.
    """
    from .models import Channel

    async with get_session_factory()() as db:
        channel = await db.get(Channel, channel_id)
        if channel is None:
            return {"posts": 0, "media": 0, "note": "channel not found"}
        return await _import_channel_content(db, channel)


async def _import_channel_content(db: AsyncSession, channel) -> dict:
    """Fetch and store one Google location's posts + gallery media.

    Never raises: a content failure must not break the connect flow or the
    review import. Returns a small summary for logging/UI.
    """
    from ..posts.models import LocationPost
    from ..media.models import LocationMedia

    # Captured before any rollback: a rollback expires every ORM object, and
    # touching channel.id afterwards would lazy-load and raise MissingGreenlet.
    cid = str(channel.id)
    access = decrypt_token(channel.access_token) if channel.access_token else None
    refresh = decrypt_token(channel.refresh_token) if channel.refresh_token else None
    if not access and not refresh:
        return {"posts": 0, "media": 0, "note": "no Google credentials"}

    account_id = (channel.platform_user_id or "").strip()
    location_id = listing_id_of(channel)
    if not account_id or not location_id:
        return {"posts": 0, "media": 0, "note": "location not configured"}

    client = GoogleReviewsClient(access or "", refresh)
    client.set_known_expiry(channel.token_expires_at)

    async def _persist(new_access: str, new_expires) -> None:
        channel.access_token = encrypt_token(new_access)
        channel.token_expires_at = new_expires
        await db.commit()

    client.set_token_persister(_persist)

    posts_created = posts_updated = 0
    media_created = media_updated = 0
    try:
        # ── Local posts ──────────────────────────────────────────────
        google_posts = await client.list_local_posts(account_id, location_id)
        existing_posts = {
            str(p.google_post_id): p
            for p in (
                await db.execute(
                    select(LocationPost).where(
                        LocationPost.user_id == channel.user_id,
                        LocationPost.google_post_id.isnot(None),
                    )
                )
            ).scalars().all()
            if p.google_post_id
        }
        for gp in google_posts:
            name = str(gp.get("name") or "")
            if not name:
                continue
            event = gp.get("event") or {}
            offer = gp.get("offer") or {}
            cta = gp.get("callToAction") or {}
            media = gp.get("media") or []
            image_urls = [
                str(m.get("sourceUrl") or "")
                for m in media
                if isinstance(m, dict) and m.get("sourceUrl")
            ][:5]
            published_at = _parse_dt(gp.get("createTime"))
            values = {
                "title": (str(gp.get("summary") or "")[:120] or "Google post"),
                "post_type": _post_type(gp),
                "description": str(gp.get("summary") or "")[:1500],
                "image_urls": image_urls,
                "cta_type": (str(cta.get("type") or "")[:32] or None) if cta else None,
                "cta_url": (str(cta.get("uri") or "")[:1000] or None) if cta else None,
                "published_at": published_at,
                "start_date": _google_date(event.get("startDate")),
                "end_date": _google_date(event.get("endDate")),
                "coupon_code": (str(offer.get("couponCode") or "")[:64] or None) if offer else None,
                "terms_conditions": (
                    str(offer.get("termsConditions") or "")[:2000] or None
                ) if offer else None,
                "google_response": {
                    "name": name,
                    "state": gp.get("state"),
                    "topicType": gp.get("topicType"),
                    "searchUrl": gp.get("searchUrl"),
                },
            }
            row = existing_posts.get(name)
            if row is None:
                db.add(LocationPost(
                    id=str(uuid.uuid4()),
                    user_id=channel.user_id,
                    listing_id=location_id,
                    location_name=channel.display_name or "",
                    business_name=channel.display_name or "",
                    google_post_id=name,
                    status=_post_status(gp),
                    **values,
                ))
                posts_created += 1
            elif row.status in ("draft", "scheduled", "archived"):
                # Merchant-authored: the merchant's own content always wins.
                # Never overwrite their text, media or status with Google's copy.
                continue
            else:
                # Google-sourced row (published/failed): refresh the mirror.
                row.status = _post_status(gp)
                for key, value in values.items():
                    setattr(row, key, value)
                row.google_post_id = name
                posts_updated += 1

        # ── Gallery media ────────────────────────────────────────────
        data = await client.list_media(account_id, location_id)
        existing_media = {
            str(m.google_post_id): m
            for m in (
                await db.execute(
                    select(LocationMedia).where(
                        LocationMedia.user_id == channel.user_id,
                        LocationMedia.google_post_id.isnot(None),
                    )
                )
            ).scalars().all()
            if m.google_post_id
        }
        for m in data.get("mediaItems") or []:
            if not isinstance(m, dict):
                continue
            name = str(m.get("name") or "")
            if not name:
                continue
            category = _media_category(m)
            method = _MEDIA_METHOD.get(category, "gallery")
            url = _media_url(m)
            if not url:
                continue
            values = {
                "image_url": url[:2000],
                "type": _MEDIA_TYPE.get(
                    str(m.get("mediaFormat") or "PHOTO").upper(), "PHOTO"
                ),
                "category": category,
                "caption": str(m.get("description") or "")[:500],
                "publish_method": method,
                "is_profile": category == "PROFILE",
                "is_cover": category == "COVER",
                "published_at": _parse_dt(m.get("createTime")),
            }
            row = existing_media.get(name)
            if row is None:
                db.add(LocationMedia(
                    id=str(uuid.uuid4()),
                    user_id=channel.user_id,
                    listing_id=location_id,
                    google_post_id=name,
                    status="published",
                    **values,
                ))
                media_created += 1
            elif row.status in ("draft", "scheduled"):
                # Merchant-authored library row: leave it alone.
                continue
            else:
                for key, value in values.items():
                    setattr(row, key, value)
                row.google_post_id = name
                row.status = "published"
                media_updated += 1

        await db.commit()
    except GoogleReviewsError as e:
        await db.rollback()
        logger.warning(
            "Google content import failed for channel %s: %s", cid, e
        )
        return {"posts": 0, "media": 0, "note": str(e)[:200]}
    except Exception as e:  # noqa: BLE001 — never break connect on content
        await db.rollback()
        logger.warning(
            "Google content import error for channel %s: %s", cid, e
        )
        return {"posts": 0, "media": 0, "note": f"{type(e).__name__}: {e}"[:200]}
    finally:
        await client.close()

    logger.info(
        "Google content import channel=%s posts +%d/+%d media +%d/+%d",
        cid, posts_created, posts_updated, media_created, media_updated,
    )
    return {
        "posts": posts_created,
        "posts_updated": posts_updated,
        "media": media_created,
        "media_updated": media_updated,
    }

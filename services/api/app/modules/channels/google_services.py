"""Push the merchant's service list to Google Business Profile.

Google treats ``serviceItems`` as a complete object: ``locations.patch`` with
``updateMask=serviceItems`` replaces the whole list and "updating individual
services is not supported". So every push rebuilds the complete list from
two sources:

- Google's own entries, carried over untouched so nothing the merchant set on
  Google's side is lost by a rebuild.
- Sayvors' custom services, sent as free-form items.

The v1 ``ServiceItem`` has no "offered" flag and a free-form item is
``{category, label}`` — the offered/not-offered state and Google's own
category services therefore stay local. Only the merchant's custom services
are published; the category's service catalogue is left as Google has it.

Sayvors is the source of truth for the custom list: a free-form service the
merchant deleted here disappears from Google's list on the next push.
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .google_reviews import GoogleReviewsError
from .models import BusinessService, Channel
from .service import decrypt_token

logger = logging.getLogger(__name__)

# Google caps a free-form service label at 140 characters and its
# description at 250.
LABEL_MAX_CHARS = 140
DESCRIPTION_MAX_CHARS = 250
# A location carries a bounded number of services.
MAX_SERVICES = 100


def _location_id_of(channel: Channel) -> str:
    """Google's location id for the channel."""
    from ..locations.service import channel_meta

    meta = channel_meta(channel)
    return str(
        meta.get("location_id")
        or channel.platform_user_id
        or channel.listing_key
        or channel.id
    )


def _free_form_name(item: dict) -> str:
    label = ((item.get("freeFormServiceItem") or {}).get("label") or {})
    return str(label.get("displayName") or "").strip()


def location_category_info(location: dict) -> tuple[str, dict[str, str]]:
    """The location's primary category id and its service types.

    Returns ``(category_id, {service display name: serviceTypeId})``. The
    service types come from the location itself, so no catalog lookup is
    needed and the ids always match the location's category.
    """
    categories = (location or {}).get("categories") or {}
    primary = categories.get("primaryCategory") or {}
    category_id = str(primary.get("name") or "").strip()
    service_ids: dict[str, str] = {}
    for service in primary.get("serviceTypes") or []:
        if not isinstance(service, dict):
            continue
        service_id = str(service.get("serviceTypeId") or "").strip()
        name = str(service.get("displayName") or "").strip()
        if service_id and name:
            service_ids[name.lower()] = service_id
    return category_id, service_ids


def _free_form_item(row: BusinessService, category_id: str) -> dict:
    """One free-form ServiceItem in the shape the v1 API accepts."""
    label: dict = {
        "displayName": str(row.name or "").strip()[:LABEL_MAX_CHARS],
        "languageCode": "en",
    }
    description = str(row.description or "").strip()
    if description:
        label["description"] = description[:DESCRIPTION_MAX_CHARS]
    return {
        "freeFormServiceItem": {
            "category": category_id,
            "label": label,
        }
    }


def build_service_items(
    *,
    google_items: list[dict],
    local_rows: list[BusinessService],
    category_id: str,
) -> tuple[list[dict], list[str]]:
    """The complete ``serviceItems`` list Google should hold.

    Returns ``(items, skipped)`` — skipped names could not be sent because
    the location has no category to file a free-form service under.
    """
    local_custom = {
        str(r.name or "").strip().lower(): r
        for r in local_rows
        if str(r.source or "") != "google" and str(r.name or "").strip()
    }
    items: list[dict] = []
    skipped: list[str] = []
    seen_free: set[str] = set()

    # Start from Google's current list so nothing the merchant set on
    # Google's side is lost by a rebuild.
    for item in google_items:
        if not isinstance(item, dict):
            continue
        free_name = _free_form_name(item)
        if not free_name:
            # A structured service: keep Google's entry untouched.
            items.append(item)
            continue
        key = free_name.lower()
        row = local_custom.get(key)
        if row is None:
            # A custom service the merchant removed in Sayvors.
            continue
        seen_free.add(key)
        items.append(_free_form_item(row, category_id))

    # Custom services Google does not hold yet.
    for key, row in local_custom.items():
        if key in seen_free:
            continue
        if not category_id:
            skipped.append(str(row.name))
            continue
        items.append(_free_form_item(row, category_id))
        seen_free.add(key)
    return items[:MAX_SERVICES], skipped


async def push_services(db: AsyncSession, channel: Channel) -> dict:
    """Push the channel's service list to Google.

    Returns ``{"pushed": bool, "error": str | None, "skipped": list[str]}``.
    Never raises: a failed push is reported, and the local rows stay as they
    are so the merchant can retry.
    """
    from .google_business import GoogleBusinessClient

    access = decrypt_token(channel.access_token) if channel.access_token else None
    refresh = decrypt_token(channel.refresh_token) if channel.refresh_token else None
    if not access and not refresh:
        return {
            "pushed": False,
            "error": "channel has no Google credentials",
            "skipped": [],
        }

    location_id = _location_id_of(channel)
    client = GoogleBusinessClient(access or "", refresh)
    try:
        rows = (
            await db.execute(
                select(BusinessService)
                .where(BusinessService.channel_id == channel.id)
                .order_by(BusinessService.created_at)
            )
        ).scalars().all()
        location = await client.get_location(location_id, read_mask="categories")
        category_id, _service_ids = location_category_info(location)
        google_items = await client.get_service_items(location_id)
        items, skipped = build_service_items(
            google_items=google_items,
            local_rows=list(rows),
            category_id=category_id,
        )
        if not items and not google_items:
            # Nothing on either side: no call to make.
            return {
                "pushed": False,
                "error": "no services to publish",
                "skipped": skipped,
            }
        # An empty rebuild still has to be sent: the services the merchant
        # deleted live here, and a skipped patch would leave them on Google.
        await client.push_service_items(location_id, items)
        return {"pushed": True, "error": None, "skipped": skipped}
    except GoogleReviewsError as e:
        logger.warning("Google service push failed for %s: %s", location_id, e)
        return {"pushed": False, "error": str(e)[:300], "skipped": []}
    except Exception as e:  # noqa: BLE001 — a push failure must not break the save
        logger.warning("Google service push error for %s: %s", location_id, e)
        return {"pushed": False, "error": str(e)[:300], "skipped": []}
    finally:
        await client.close()

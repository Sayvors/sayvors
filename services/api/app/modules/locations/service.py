"""Locations backing service.

Merges the Google-synced snapshot (Localith connection) with the locally
stored profile (categories, hours, service area, attributes, description).
Google-writable fields are pushed through the Localith API; everything
else persists in `location_profiles`.
"""
import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..localith.models import LocalithConnection
from .models import LocationProfile

logger = logging.getLogger(__name__)

GOOGLE_SYNCED_FIELDS = ["name", "phone", "website", "description"]


async def _connection(db: AsyncSession, user_id: str) -> LocalithConnection | None:
    result = await db.execute(
        select(LocalithConnection).where(LocalithConnection.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def _profile(db: AsyncSession, user_id: str, listing_id: str) -> LocationProfile:
    try:
        result = await db.execute(
            select(LocationProfile).where(
                LocationProfile.user_id == user_id,
                LocationProfile.listing_id == listing_id,
            )
        )
        profile = result.scalar_one_or_none()
        if profile is None:
            profile = LocationProfile(user_id=user_id, listing_id=listing_id)
            db.add(profile)
            await db.flush()
        return profile
    except Exception as e:
        # Table missing on dev DBs that haven't run migrations — don't 500 the page.
        if "UndefinedTableError" in type(e).__name__ or "does not exist" in str(e):
            logger.debug("location_profiles missing, returning ephemeral profile: %s", e)
            try:
                await db.rollback()
            except Exception:
                pass
            return LocationProfile(user_id=user_id, listing_id=listing_id)
        raise


def _status_of(connection: LocalithConnection | None) -> str:
    if connection is None:
        return "unknown"
    if connection.is_suspended:
        return "suspended"
    if connection.is_verified:
        return "active"
    return "pending"


async def get_profile(
    db: AsyncSession, user_id: str, listing_id: str
) -> dict:
    """Merged profile for one listing (auto-creates the local row)."""
    try:
        profile = await _profile(db, user_id, listing_id)
        await db.commit()
    except Exception as e:
        if "UndefinedTableError" in type(e).__name__ or "does not exist" in str(e):
            logger.debug("get_profile fallback for missing table: %s", e)
            try:
                await db.rollback()
            except Exception:
                pass
            # Return ephemeral in-memory profile so the page still loads
            profile = LocationProfile(user_id=user_id, listing_id=listing_id)
        else:
            raise

    # Fetch after the try/except: the missing-table fallback in _profile
    # rolls the session back, and rollback expires every loaded object.
    # Touching an expired attribute below would trigger a sync lazy-load
    # (MissingGreenlet); a fresh select repopulates it inside the await.
    connection = await _connection(db, user_id)

    merged = {
        "listing_id": listing_id,
        "name": "",
        "address": None,
        "phone": None,
        "website": None,
        "maps_url": None,
        "status": "unknown",
        "is_verified": None,
        "description": profile.description,
        "categories": dict(profile.categories or {}),
        "hours": dict(profile.hours or {}),
        "service_area": list(profile.service_area or []),
        "attributes": dict(profile.attributes or {}),
        "google_synced": [],
        "updated_at": profile.updated_at.isoformat() if profile.updated_at else None,
    }
    if connection is not None and connection.listing_id == listing_id:
        merged.update({
            "name": connection.listing_name,
            "address": connection.address,
            "phone": connection.phone_number,
            "website": connection.website_url,
            "maps_url": connection.maps_url,
            "status": _status_of(connection),
            "is_verified": connection.is_verified,
            "google_synced": list(GOOGLE_SYNCED_FIELDS),
        })
    return merged


async def update_profile(
    db: AsyncSession,
    user_id: str,
    listing_id: str,
    description: str | None,
    categories: dict | None,
    hours: dict | None,
    service_area: list | None,
    attributes: dict | None,
) -> dict:
    """Update a profile. Description pushes to Google when connected."""
    from ..localith import service as localith_service

    connection = await _connection(db, user_id)
    profile = await _profile(db, user_id, listing_id)

    if description is not None:
        description = description[:750]
        if connection is not None and connection.listing_id == listing_id:
            try:
                await asyncio.to_thread(
                    localith_service.embedsocial.update_listing,
                    listing_id,
                    {"description": description},
                )
            except ValueError:
                pass  # empty after trim — keep local value only
            except Exception as e:
                raise RuntimeError(f"Google update failed: {e}")
        profile.description = description
    if categories is not None:
        merged_cats = dict(profile.categories or {})
        if categories.get("primary") is not None:
            merged_cats["primary"] = str(categories.get("primary", ""))[:255]
        if categories.get("additional") is not None:
            merged_cats["additional"] = [str(c)[:255] for c in categories.get("additional", [])][:50]
        profile.categories = merged_cats
    if hours is not None:
        merged_hours = dict(profile.hours or {})
        if hours.get("regular") is not None:
            merged_hours["regular"] = dict(hours.get("regular", {}))
        if hours.get("special") is not None:
            merged_hours["special"] = list(hours.get("special", []))[:100]
        if hours.get("more") is not None:
            merged_hours["more"] = list(hours.get("more", []))[:100]
        profile.hours = merged_hours
    if service_area is not None:
        profile.service_area = [str(a)[:255] for a in service_area][:100]
    if attributes is not None:
        profile.attributes = {
            str(k)[:120]: str(v)[:500] for k, v in list(attributes.items())[:100]
        }
    profile.updated_at = datetime.now(timezone.utc)
    await db.commit()
    return await get_profile(db, user_id, listing_id)

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

from ...core.providers import GOOGLE, locations_write_provider
from ..localith.models import LocalithConnection
from .models import LocationProfile

logger = logging.getLogger(__name__)

GOOGLE_SYNCED_FIELDS = ["name", "phone", "website", "description"]


async def _connection(
    db: AsyncSession, user_id: str, listing_id: str | None = None
) -> LocalithConnection | None:
    result = await db.execute(
        select(LocalithConnection).where(LocalithConnection.user_id == user_id)
    )
    connections = list(result.scalars().all())
    if listing_id:
        return next((c for c in connections if c.listing_id == listing_id), None)
    return connections[0] if connections else None


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
    connection = await _connection(db, user_id, listing_id)

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
        "opening_date": profile.opening_date.isoformat() if profile.opening_date else None,
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


async def _native_channel_for_listing(
    db: AsyncSession, user_id: str, listing_id: str
):
    """The tenant's native Google channel for this listing (OAuth tokens),
    or None. Matched on channel metadata location_id / platform_user_id."""
    import json as _json

    from sqlalchemy import select as _select

    from ..channels.models import Channel

    rows = (
        await db.execute(
            _select(Channel).where(
                Channel.user_id == user_id,
                Channel.platform == "google_reviews",
                Channel.status == "active",
            )
        )
    ).scalars().all()
    for ch in rows:
        try:
            meta = ch.metadata_json
            meta = _json.loads(meta) if isinstance(meta, str) else (meta or {})
        except Exception:
            meta = {}
        if meta.get("location_id") == listing_id or ch.platform_user_id == listing_id:
            return ch
    return None


async def _push_profile_native(
    db: AsyncSession, user_id: str, listing_id: str, profile: LocationProfile
) -> list[str]:
    """Best-effort native push of all stored sections. Returns pushed names.

    Local storage stays the source of truth regardless — a rejected section
    is logged (never raised), so one bad section can't fail the save.
    """
    from ..channels.google_business import GoogleBusinessClient
    from ..channels.service import decrypt_token

    channel = await _native_channel_for_listing(db, user_id, listing_id)
    if channel is None:
        logger.warning(
            "Native locations push skipped for %s: no Google channel connected",
            listing_id)
        return []
    access = decrypt_token(channel.access_token) if channel.access_token else None
    refresh = decrypt_token(channel.refresh_token) if channel.refresh_token else None
    if not access and not refresh:
        logger.warning(
            "Native locations push skipped for %s: channel has no tokens",
            listing_id)
        return []
    # Google location id: metadata location_id, else the listing id itself.
    import json as _json

    try:
        meta = channel.metadata_json
        meta = _json.loads(meta) if isinstance(meta, str) else (meta or {})
    except Exception:
        meta = {}
    google_id = meta.get("location_id") or listing_id
    client = GoogleBusinessClient(access or "", refresh)
    try:
        report = await client.push_profile(
            google_id,
            description=profile.description,
            categories=dict(profile.categories or {}),
            hours=dict(profile.hours or {}),
            opening_date=profile.opening_date.isoformat() if profile.opening_date else None,
            attributes=dict(profile.attributes or {}),
        )
    except Exception as e:
        logger.warning("Native locations push failed for %s: %s", listing_id, e)
        return []
    finally:
        await client.close()
    for section, reason in (report.get("skipped") or {}).items():
        logger.warning("Native locations push skipped %s for %s: %s",
                       section, listing_id, reason)
    return report.get("pushed", [])


async def update_profile(
    db: AsyncSession,
    user_id: str,
    listing_id: str,
    description: str | None,
    categories: dict | None,
    hours: dict | None,
    service_area: list | None,
    attributes: dict | None,
    opening_date: str | None = None,
) -> dict:
    """Update a profile. Description pushes to Google when connected
    (Localith path, legacy behavior: push failure aborts the save).

    Native path (LOCATIONS_WRITE_PROVIDER=google): local save always
    lands first, then every stored section pushes best-effort; per-section
    results land in `google_synced` and failures only log.
    """
    import datetime as _dt

    from ..localith import service as localith_service

    connection = await _connection(db, user_id, listing_id)
    profile = await _profile(db, user_id, listing_id)

    provider = locations_write_provider()
    if description is not None:
        description = description[:750]
        if provider == GOOGLE:
            pass  # pushed natively after the local save below
        elif connection is not None and connection.listing_id == listing_id:
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
    if opening_date is not None:
        try:
            profile.opening_date = _dt.date.fromisoformat(str(opening_date))
        except ValueError:
            raise ValueError(f"Invalid opening_date {opening_date!r}, use YYYY-MM-DD")
    profile.updated_at = datetime.now(timezone.utc)
    await db.commit()

    pushed: list[str] = []
    if provider == GOOGLE:
        pushed = await _push_profile_native(db, user_id, listing_id, profile)
    elif description is not None and connection is not None and connection.listing_id == listing_id:
        pushed = ["description"]
    out = await get_profile(db, user_id, listing_id)
    out["google_synced"] = pushed
    return out

"""Merchant-edited business details per Google location.

Google's Business Profile values (name, categories, hours) can be stale or
still pending review at Google. The merchant can correct them here; those
values are what the AI's facts use, while the official Google values are kept
in the row for a side-by-side compare.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..locations.models import LocationBusinessOverride, LocationProfile
from ..locations.service import channel_meta, listing_id_of, native_channels
from .facts_store import rebuild_facts_safe

logger = logging.getLogger(__name__)

_EMPTY = {"name": "", "address": "", "website": "", "categories": {}, "hours": {}, "services": [], "special_hours": []}


def _serialize_google(channel, profile: LocationProfile | None) -> dict:
    meta = channel_meta(channel)
    return {
        "name": (channel.display_name or "").strip(),
        "address": str(meta.get("address") or "").strip(),
        "website": str(meta.get("website") or "").strip(),
        "categories": dict(profile.categories or {}) if profile else {},
        "hours": dict(profile.hours or {}) if profile else {},
        "services": [],
        "special_hours": [],
    }


def _serialize_user(row: LocationBusinessOverride | None) -> dict | None:
    if row is None:
        return None
    return {
        "name": row.name,
        "categories": dict(row.categories or {}),
        "services": list(row.services or []),
        "hours": dict(row.hours or {}),
        "special_hours": list(row.special_hours or []),
        "source": row.source,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def get_all_details(db: AsyncSession, tenant_id: str) -> list[dict]:
    """Every native Google location with its official + merchant values."""
    channels = await native_channels(db, tenant_id, statuses=("active", "expired"))
    if not channels:
        return []

    profiles = {
        str(p.listing_id): p
        for p in (
            await db.execute(
                select(LocationProfile).where(LocationProfile.user_id == tenant_id)
            )
        ).scalars().all()
    }
    overrides = {
        str(o.listing_id): o
        for o in (
            await db.execute(
                select(LocationBusinessOverride).where(LocationBusinessOverride.user_id == tenant_id)
            )
        ).scalars().all()
    }

    out = []
    for ch in channels:
        listing_id = listing_id_of(ch)
        out.append({
            "listing_id": listing_id,
            "google": _serialize_google(ch, profiles.get(listing_id)),
            "user": _serialize_user(overrides.get(listing_id)),
        })
    return out


async def save_details(
    db: AsyncSession,
    tenant_id: str,
    listing_id: str,
    *,
    name: str | None,
    categories: dict | None,
    services: list | None,
    hours: dict | None,
    special_hours: list | None,
) -> dict:
    """Upsert merchant overrides for one location and rebuild the AI facts."""
    channels = await native_channels(db, tenant_id, statuses=("active", "expired"))
    channel = next((c for c in channels if listing_id_of(c) == listing_id), None)
    if channel is None:
        raise ValueError("Location not found for this account.")

    profile = (
        await db.execute(
            select(LocationProfile).where(
                LocationProfile.user_id == tenant_id,
                LocationProfile.listing_id == listing_id,
            )
        )
    ).scalar_one_or_none()

    row = (
        await db.execute(
            select(LocationBusinessOverride).where(
                LocationBusinessOverride.user_id == tenant_id,
                LocationBusinessOverride.listing_id == listing_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = LocationBusinessOverride(user_id=tenant_id, listing_id=listing_id)
        db.add(row)

    # Freeze the official Google values so the compare view survives edits.
    row.google_snapshot = _serialize_google(channel, profile)
    if name is not None:
        row.name = name.strip() or None
    if categories is not None:
        row.categories = categories
    if services is not None:
        row.services = [s for s in services if s]
    if hours is not None:
        row.hours = hours
    if special_hours is not None:
        row.special_hours = special_hours
    row.source = "edited"
    row.updated_at = datetime.now(timezone.utc)
    await db.commit()

    await rebuild_facts_safe(db, tenant_id)
    return {
        "listing_id": listing_id,
        "google": row.google_snapshot,
        "user": _serialize_user(row),
    }

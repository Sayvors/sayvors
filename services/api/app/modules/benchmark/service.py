"""Tenant-scoped bench CRUD with hard caps.

A saved place belongs to one tenant's bench. Everything here is scoped by
tenant_id in the query itself, so a cross-tenant read is impossible by
construction rather than by convention.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .models import BenchmarkConfig, BenchmarkPlace

MAX_LABEL = 120
MAX_NOTES = 2000
MAX_LIST = 100


class BenchError(ValueError):
    """A validation or quota failure safe to show to the tenant."""


async def get_config(db: AsyncSession) -> BenchmarkConfig:
    """Single config row, created with defaults on first use."""
    row = (
        await db.execute(select(BenchmarkConfig).where(BenchmarkConfig.id == "default"))
    ).scalar_one_or_none()
    if row is None:
        row = BenchmarkConfig(id="default")
        db.add(row)
        await db.commit()
        await db.refresh(row)
    return row


def serialize(place: BenchmarkPlace) -> dict:
    return {
        "id": place.id,
        "place_id": place.place_id,
        "label": place.label,
        "notes": place.notes,
        "in_heatmap": place.in_heatmap,
        "name": place.name,
        "address": getattr(place, "address", None),
        "rating": place.rating,
        "review_count": place.review_count,
        "latitude": place.latitude,
        "longitude": place.longitude,
        "reviews": place.reviews,
        "photos": place.photos,
        "fetched_at": place.fetched_at.isoformat() if place.fetched_at else None,
        "created_at": place.created_at.isoformat() if place.created_at else None,
        "updated_at": place.updated_at.isoformat() if place.updated_at else None,
    }


async def save_place(
    db: AsyncSession,
    tenant_id: str,
    *,
    place_id: str,
    label: str | None = None,
    notes: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
) -> BenchmarkPlace:
    """Save one place to this tenant's bench, idempotent on (tenant, place)."""
    pid = str(place_id or "").strip()[:255]
    if not pid:
        raise BenchError("Choose a place to save.")
    clean_label = (label or "").strip()[:MAX_LABEL] or None
    clean_notes = (notes or "").strip()[:MAX_NOTES] or None

    dup = (
        await db.execute(
            select(BenchmarkPlace).where(
                BenchmarkPlace.tenant_id == tenant_id,
                BenchmarkPlace.place_id == pid,
            )
        )
    ).scalar_one_or_none()
    if dup is not None:
        if clean_label is not None:
            dup.label = clean_label
        if clean_notes is not None:
            dup.notes = clean_notes
        if latitude is not None and longitude is not None:
            dup.latitude, dup.longitude = latitude, longitude
        await db.commit()
        await db.refresh(dup)
        return dup

    config = await get_config(db)
    used = (
        await db.execute(
            select(func.count(BenchmarkPlace.id)).where(
                BenchmarkPlace.tenant_id == tenant_id
            )
        )
    ).scalar() or 0
    if int(used) >= config.max_saved_places:
        raise BenchError(
            f"Your bench holds {config.max_saved_places} places. Remove one before saving another."
        )

    row = BenchmarkPlace(
        tenant_id=tenant_id, place_id=pid,
        label=clean_label, notes=clean_notes,
        latitude=latitude, longitude=longitude,
    )
    db.add(row)
    try:
        await db.commit()
    except IntegrityError as exc:  # concurrent save of the same place
        await db.rollback()
        existing = (
            await db.execute(
                select(BenchmarkPlace).where(
                    BenchmarkPlace.tenant_id == tenant_id,
                    BenchmarkPlace.place_id == pid,
                )
            )
        ).scalar_one_or_none()
        if existing is None:
            raise BenchError("Could not save this place.") from exc
        return existing
    await db.refresh(row)
    return row


async def list_saved(
    db: AsyncSession, tenant_id: str, *, limit: int = MAX_LIST
) -> list[dict]:
    rows = (
        await db.execute(
            select(BenchmarkPlace)
            .where(BenchmarkPlace.tenant_id == tenant_id)
            .order_by(BenchmarkPlace.created_at.desc())
            .limit(max(1, min(int(limit), MAX_LIST)))
        )
    ).scalars().all()
    return [serialize(row) for row in rows]


async def get_saved(db: AsyncSession, tenant_id: str, place_id: str) -> BenchmarkPlace | None:
    """Fetch one saved place, scoped to this tenant. None means not on their bench."""
    return (
        await db.execute(
            select(BenchmarkPlace).where(
                BenchmarkPlace.tenant_id == tenant_id,
                BenchmarkPlace.place_id == str(place_id or "")[:255],
            )
        )
    ).scalar_one_or_none()


async def toggle_heatmap(
    db: AsyncSession, tenant_id: str, place_id: str, *, enabled: bool | None = None
) -> BenchmarkPlace | None:
    """Include or exclude a saved place from the heatmap (tenant-scoped)."""
    row = await get_saved(db, tenant_id, place_id)
    if row is None:
        return None
    row.in_heatmap = (not row.in_heatmap) if enabled is None else bool(enabled)
    await db.commit()
    await db.refresh(row)
    return row


async def delete_saved(db: AsyncSession, tenant_id: str, place_id: str) -> bool:
    row = (
        await db.execute(
            select(BenchmarkPlace).where(
                BenchmarkPlace.tenant_id == tenant_id,
                BenchmarkPlace.place_id == str(place_id or "")[:255],
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return False
    await db.delete(row)
    await db.commit()
    return True

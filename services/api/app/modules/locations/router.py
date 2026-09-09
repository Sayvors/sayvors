"""Locations API — list, read and update business locations.

GET    /api/v1/locations/                list (Localith listing + Google channels)
GET    /api/v1/locations/{listing_id}    merged profile (Google snapshot + local store)
PUT    /api/v1/locations/{listing_id}    update (description pushes to Google)
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.deps import get_current_user, get_db
from ..channels.models import Channel
from ..users.models import User
from . import service
from .schemas import LocationProfileOut, LocationSummary, LocationUpdate

router = APIRouter(prefix="/api/v1/locations", tags=["locations"])


@router.get("/", response_model=list[LocationSummary])
async def list_locations(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from ..localith.models import LocalithConnection

    out: list[LocationSummary] = []
    result = await db.execute(
        select(LocalithConnection).where(LocalithConnection.user_id == user.id)
    )
    connection = result.scalar_one_or_none()
    if connection is not None:
        out.append(LocationSummary(
            listing_id=connection.listing_id,
            name=connection.listing_name,
            address=connection.address,
            status=service._status_of(connection),
            source="localith",
        ))
    channels = (
        await db.execute(
            select(Channel).where(
                Channel.user_id == user.id,
                Channel.platform == "google_reviews",
                Channel.status == "active",
            )
        )
    ).scalars().all()
    seen = {c.listing_id for c in [connection] if c}
    for ch in channels:
        if ch.platform_user_id and ch.platform_user_id not in seen:
            out.append(LocationSummary(
                listing_id=ch.id,
                name=ch.display_name or "Google location",
                address=None,
                status=ch.status,
                source="channel",
            ))
    return out


@router.get("/{listing_id}", response_model=LocationProfileOut)
async def get_location(
    listing_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await service.get_profile(db, user.id, listing_id)


@router.put("/{listing_id}", response_model=LocationProfileOut)
async def update_location(
    listing_id: str,
    body: LocationUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await service.update_profile(
            db,
            user.id,
            listing_id,
            description=body.description,
            categories=body.categories.model_dump() if body.categories else None,
            hours=body.hours.model_dump() if body.hours else None,
            service_area=body.service_area,
            attributes=body.attributes,
        )
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))

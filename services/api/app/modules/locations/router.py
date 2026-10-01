"""Locations API — list, read and update business locations.

GET    /api/v1/locations/                list (Localith listing + Google channels)
GET    /api/v1/locations/groups          named sets of listings for bulk actions
POST   /api/v1/locations/groups          create a group
PATCH  /api/v1/locations/groups/{id}     rename / change members
DELETE /api/v1/locations/groups/{id}     delete a group
GET    /api/v1/locations/{listing_id}    merged profile (Google snapshot + local store)
PUT    /api/v1/locations/{listing_id}    update (description pushes to Google)
"""
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.deps import get_current_user, get_db
from ..channels.models import Channel
from ..users.models import User
from . import service
from .schemas import (
    LocationGroupIn,
    LocationGroupOut,
    LocationGroupUpdate,
    LocationProfileOut,
    LocationSummary,
    LocationUpdate,
)

router = APIRouter(prefix="/api/v1/locations", tags=["locations"])


@router.get("/", response_model=list[LocationSummary])
async def list_locations(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from ..localith.models import LocalithConnection

    out: list[LocationSummary] = []
    result = await db.execute(
        select(LocalithConnection)
        .where(LocalithConnection.user_id == user.id)
        .order_by(LocalithConnection.created_at)
    )
    connections = list(result.scalars().all())
    for connection in connections:
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
    seen = {c.listing_id for c in connections}
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


# Declared before /{listing_id} so "groups" is never swallowed as a listing ID.
@router.get("/groups", response_model=list[LocationGroupOut])
async def list_location_groups(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await service.list_groups(db, user.id)


@router.post("/groups", response_model=LocationGroupOut, status_code=201)
async def create_location_group(
    body: LocationGroupIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await service.create_group(db, user.id, body.name, body.listing_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.patch("/groups/{group_id}", response_model=LocationGroupOut)
async def update_location_group(
    group_id: str,
    body: LocationGroupUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        out = await service.update_group(db, user.id, group_id, body.name, body.listing_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if out is None:
        raise HTTPException(status_code=404, detail="Group not found")
    return out


@router.delete("/groups/{group_id}", status_code=204)
async def delete_location_group(
    group_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not await service.delete_group(db, user.id, group_id):
        raise HTTPException(status_code=404, detail="Group not found")
    return Response(status_code=204)


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
            opening_date=body.opening_date.isoformat() if body.opening_date else None,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))

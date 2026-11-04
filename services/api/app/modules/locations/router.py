"""Locations API — list, read and update business locations.

GET    /api/v1/locations/                list native Google listings
GET    /api/v1/locations/groups          named sets of listings for bulk actions
POST   /api/v1/locations/groups          create a group
PATCH  /api/v1/locations/groups/{id}     rename / change members
DELETE /api/v1/locations/groups/{id}     delete a group
GET    /api/v1/locations/{listing_id}    merged profile (Google snapshot + local store)
PUT    /api/v1/locations/{listing_id}    update (description pushes to Google)
"""
from fastapi import APIRouter, Depends, HTTPException, Response, UploadFile, File
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.deps import get_current_user, get_db
from ...core.upstream_errors import upstream_http_error
from ..users.models import User
from . import service
from . import bulk as bulk_service
from .schemas import (
    LocationGroupIn,
    LocationGroupOut,
    LocationGroupUpdate,
    LocationProfileOut,
    LocationSummary,
    LocationUpdate,
)
from ..team.context import tenant_id_of, require_perm, TenantContext

router = APIRouter(prefix="/api/v1/locations", tags=["locations"])


@router.get("", response_model=list[LocationSummary])
async def list_locations(
    ctx: TenantContext = Depends(require_perm("locations.view")),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Every native Google listing for the tenant, with live review stats."""
    from sqlalchemy import func

    from ..analytics.models import ReviewInsight

    uid = tenant_id_of(user)
    channels = await service.native_channels(
        db, uid, statuses=("active", "expired")
    )
    stats: dict[str, tuple[float | None, int]] = {}
    if channels:
        rows = (
            await db.execute(
                select(
                    ReviewInsight.channel_id,
                    func.avg(ReviewInsight.rating),
                    func.count(),
                )
                .where(
                    ReviewInsight.channel_id.in_([ch.id for ch in channels]),
                    ReviewInsight.removed_at.is_(None),
                )
                .group_by(ReviewInsight.channel_id)
            )
        ).all()
        stats = {
            channel_id: (float(avg) if avg is not None else None, int(total))
            for channel_id, avg, total in rows
        }

    out: list[LocationSummary] = []
    for channel in channels:
        meta = service.channel_meta(channel)
        rating, reviews = stats.get(channel.id, (None, 0))
        out.append(LocationSummary(
            listing_id=service.listing_id_of(channel),
            name=channel.display_name or "Google location",
            address=meta.get("address"),
            phone=meta.get("phone"),
            website=meta.get("website"),
            maps_url=meta.get("maps_url"),
            status=channel.status,
            rating=rating,
            reviews=reviews,
            source="google",
        ))
    return out


# Declared before /{listing_id} so "groups" is never swallowed as a listing ID.
@router.get("/groups", response_model=list[LocationGroupOut])
async def list_location_groups(
    ctx: TenantContext = Depends(require_perm("locations.view")),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await service.list_groups(db, tenant_id_of(user))


@router.post("/groups", response_model=LocationGroupOut, status_code=201)
async def create_location_group(
    body: LocationGroupIn,
    ctx: TenantContext = Depends(require_perm("locations.view")),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await service.create_group(db, tenant_id_of(user), body.name, body.listing_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.patch("/groups/{group_id}", response_model=LocationGroupOut)
async def update_location_group(
    group_id: str,
    body: LocationGroupUpdate,
    ctx: TenantContext = Depends(require_perm("locations.view")),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        out = await service.update_group(db, tenant_id_of(user), group_id, body.name, body.listing_ids)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if out is None:
        raise HTTPException(status_code=404, detail="Group not found")
    return out


@router.delete("/groups/{group_id}", status_code=204)
async def delete_location_group(
    group_id: str,
    ctx: TenantContext = Depends(require_perm("locations.view")),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not await service.delete_group(db, tenant_id_of(user), group_id):
        raise HTTPException(status_code=404, detail="Group not found")
    return Response(status_code=204)


@router.get("/bulk-data")
async def get_bulk_data(
    ctx: TenantContext = Depends(require_perm("locations.view")),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return current listing data as JSON for the in-browser spreadsheet editor."""
    return await bulk_service.build_template_data(db, tenant_id_of(user))

@router.get("/bulk-template")
async def download_bulk_template(
    ctx: TenantContext = Depends(require_perm("locations.view")),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Download a CSV template pre-filled with current listing data."""
    csv_text = await bulk_service.build_template_csv(db, tenant_id_of(user))
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="locations_bulk_template.csv"'},
    )


@router.post("/bulk-upload")
async def upload_bulk_csv(
    file: UploadFile = File(...),
    ctx: TenantContext = Depends(require_perm("locations.view")),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload a CSV file to bulk-update listing information."""
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="File must be a .csv")
    content = await file.read()
    if len(content) > bulk_service.MAX_FILE_BYTES:
        raise HTTPException(status_code=413, detail=f"File too large (max {bulk_service.MAX_FILE_BYTES // (1024*1024)} MB)")
    try:
        csv_text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="File must be UTF-8 encoded")
    try:
        report = await bulk_service.apply_bulk_csv(db, tenant_id_of(user), csv_text)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return report

@router.get("/{listing_id}", response_model=LocationProfileOut)
async def get_location(
    listing_id: str,
    ctx: TenantContext = Depends(require_perm("locations.view")),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await service.get_profile(db, tenant_id_of(user), listing_id)


@router.put("/{listing_id}", response_model=LocationProfileOut)
async def update_location(
    listing_id: str,
    body: LocationUpdate,
    ctx: TenantContext = Depends(require_perm("locations.view")),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await service.update_profile(
            db,
            tenant_id_of(user),
            listing_id,
            description=body.description,
            categories=body.categories.model_dump() if body.categories else None,
            hours=body.hours.model_dump() if body.hours else None,
            service_area=body.service_area,
            attributes=body.attributes,
            opening_date=body.opening_date.isoformat() if body.opening_date else None,
            name=body.name,
            phone=body.phone,
            website=body.website,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise upstream_http_error(e, context="Location provider failed") from None

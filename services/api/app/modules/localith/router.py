"""Localith connect flow — single-shared-key mode.

The API key is configured server-side (LOCALITH_API_KEY). Each Sayvors user
saves *one* location_id chosen from their Localith account. Per-tenant
keys can be added later by extending LocalithConnection with an encrypted
key column.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.deps import get_current_user, get_db
from ..users.models import User
from . import service
from .models import LocalithConnection

router = APIRouter(prefix="/api/v1/integrations/localith", tags=["localith"])


class ConnectionCreate(BaseModel):
    listing_id: str = Field(..., min_length=1, max_length=64)
    listing_name: str = Field(..., min_length=1, max_length=255)
    listing_google_id: str | None = Field(None, max_length=128)


class ConnectionResponse(BaseModel):
    id: str
    listing_id: str
    listing_name: str
    listing_google_id: str | None
    last_synced_at: str | None
    created_at: str
    # ── profile snapshot ──
    address: str | None = None
    phone_number: str | None = None
    website_url: str | None = None
    maps_url: str | None = None
    store_code: str | None = None
    is_verified: bool | None = None
    is_disabled: bool | None = None
    is_suspended: bool | None = None
    total_reviews: int = 0
    average_rating: float = 0.0
    last_review_on: str | None = None
    last_reply_on: str | None = None
    profile_synced_at: str | None = None
    # ── metrics window ──
    metrics_start: str | None = None
    metrics_end: str | None = None
    metrics_synced_at: str | None = None


def _serialize(c: LocalithConnection) -> ConnectionResponse:
    return ConnectionResponse(
        id=c.id,
        listing_id=c.listing_id,
        listing_name=c.listing_name,
        listing_google_id=c.listing_google_id,
        last_synced_at=c.last_synced_at.isoformat() if c.last_synced_at else None,
        created_at=c.created_at.isoformat(),
        address=c.address,
        phone_number=c.phone_number,
        website_url=c.website_url,
        maps_url=c.maps_url,
        store_code=c.store_code,
        is_verified=c.is_verified,
        is_disabled=c.is_disabled,
        is_suspended=c.is_suspended,
        total_reviews=c.total_reviews or 0,
        average_rating=c.average_rating or 0.0,
        last_review_on=c.last_review_on.isoformat() if c.last_review_on else None,
        last_reply_on=c.last_reply_on.isoformat() if c.last_reply_on else None,
        profile_synced_at=c.profile_synced_at.isoformat() if c.profile_synced_at else None,
        metrics_start=c.metrics_start.isoformat() if c.metrics_start else None,
        metrics_end=c.metrics_end.isoformat() if c.metrics_end else None,
        metrics_synced_at=c.metrics_synced_at.isoformat() if c.metrics_synced_at else None,
    )


@router.get("/config")
async def config_status(_user: User = Depends(get_current_user)):
    """Returns whether the server is configured (key present) for the UI."""
    return {"configured": service._key_present()}


@router.get("/listings")
async def get_local_listings(
    _user: User = Depends(get_current_user),
):
    """List the locations available under the configured Localith account."""
    try:
        listings = await service.list_local_listings()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Localith listings request failed: {type(e).__name__}: {e}")
    return {"listings": listings}


@router.post("/test")
async def test_listing(
    body: ConnectionCreate,
    _user: User = Depends(get_current_user),
):
    """Probe a listing id against Localith (returns one sample item if any)."""
    try:
        items = await service.list_local_items(body.listing_id, limit=1)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Localith rejected listing: {e}")
    return {"ok": True, "sample_count": len(items)}


@router.post("/sync")
async def sync_my_connection(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Sync the selected Localith listing into the normal Sayvors pipeline."""
    try:
        return await service.sync_connection(user, db)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Localith sync failed: {e}")


@router.get("/connection", response_model=ConnectionResponse | None)
async def get_my_connection(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(LocalithConnection).where(LocalithConnection.user_id == user.id)
    )
    c = result.scalar_one_or_none()
    return _serialize(c) if c else None


class ProfileSnapshot(BaseModel):
    connection: ConnectionResponse
    listing: dict
    metrics: dict
    item_metrics: dict


@router.get("/profile", response_model=ProfileSnapshot | None)
async def get_my_profile(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Full synced snapshot: profile detail + both metrics summaries."""
    result = await db.execute(
        select(LocalithConnection).where(LocalithConnection.user_id == user.id)
    )
    c = result.scalar_one_or_none()
    if c is None:
        return None
    return ProfileSnapshot(
        connection=_serialize(c),
        listing=c.raw_listing_json or {},
        metrics=c.raw_metrics_json or {},
        item_metrics=c.raw_item_metrics_json or {},
    )


@router.put("/connection", response_model=ConnectionResponse)
async def save_connection(
    body: ConnectionCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(LocalithConnection).where(LocalithConnection.user_id == user.id)
    )
    c = result.scalar_one_or_none()
    if c is None:
        c = LocalithConnection(
            id=__import__("uuid").uuid4().hex,
            user_id=user.id,
            listing_id=body.listing_id,
            listing_name=body.listing_name,
            listing_google_id=body.listing_google_id,
        )
        db.add(c)
    else:
        c.listing_id = body.listing_id
        c.listing_name = body.listing_name
        c.listing_google_id = body.listing_google_id
    await db.commit()
    await db.refresh(c)
    return _serialize(c)


class ListingUpdate(BaseModel):
    name: str | None = Field(None, max_length=255)
    description: str | None = Field(None, max_length=2000)
    phone_number: str | None = Field(None, max_length=64)
    website_url: str | None = Field(None, max_length=500)
    city: str | None = Field(None, max_length=255)
    country: str | None = Field(None, max_length=8)
    street: str | None = Field(None, max_length=500)


@router.patch("/listing", response_model=ConnectionResponse)
async def update_my_listing(
    body: ListingUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update the connected listing (writes back to Google via Localith),
    then refresh the stored profile snapshot."""
    import asyncio

    result = await db.execute(
        select(LocalithConnection).where(LocalithConnection.user_id == user.id)
    )
    c = result.scalar_one_or_none()
    if c is None:
        raise HTTPException(status_code=400, detail="Connect a Localith listing first.")
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if not fields:
        raise HTTPException(status_code=400, detail="No fields to update.")
    try:
        await asyncio.to_thread(service.embedsocial.update_listing, c.listing_id, fields)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Localith update failed: {e}")
    try:
        detail = await service.get_listing_detail(c.listing_id)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Updated, but re-fetch failed: {e}")
    if detail:
        service.apply_listing_snapshot(c, detail)
    c.last_synced_at = service.now_utc()
    await db.commit()
    await db.refresh(c)
    return _serialize(c)


@router.delete("/connection", status_code=204)
async def delete_my_connection(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(LocalithConnection).where(LocalithConnection.user_id == user.id)
    )
    c = result.scalar_one_or_none()
    if c is not None:
        await db.delete(c)
        await db.commit()

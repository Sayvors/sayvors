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


def _serialize(c: LocalithConnection) -> ConnectionResponse:
    return ConnectionResponse(
        id=c.id,
        listing_id=c.listing_id,
        listing_name=c.listing_name,
        listing_google_id=c.listing_google_id,
        last_synced_at=c.last_synced_at.isoformat() if c.last_synced_at else None,
        created_at=c.created_at.isoformat(),
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

"""Localith connect flow — per-tenant API keys (Fernet-encrypted on the
connection rows) with the shared LOCALITH_API_KEY env as fallback.

Each Sayvors user saves *one* location_id chosen from their Localith
account. The tenant's API key is account-wide, so setting it writes the
same ciphertext to every connection row the user owns.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.deps import get_current_user, get_db
from ..analytics.models import ReviewInsight
from ..channels.models import AutoReplyConfig, Channel, ChannelMessage, ReviewReply
from ..channels.service import encrypt_token as _encrypt_localith_key
from ..locations.models import LocationProfile
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
    # Per-tenant key present (account-wide for this user's rows). Never the key itself.
    has_api_key: bool = False


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
        has_api_key=bool(getattr(c, "api_key_encrypted", None)),
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
        # Log the cause, return an opaque message — provider errors can
        # leak account/topology details to clients.
        import logging

        logging.getLogger(__name__).warning("Localith listings failed: %s", e)
        raise HTTPException(status_code=502, detail="Localith listings request failed")
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
        import logging

        logging.getLogger(__name__).warning("Localith listing probe failed: %s", e)
        raise HTTPException(status_code=502, detail="Localith rejected the listing")
    return {"ok": True, "sample_count": len(items)}


@router.post("/sync")
async def sync_my_connection(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    listing_id: str | None = None,
):
    """Sync Localith listings into the normal Sayvors pipeline.

    With listing_id set, syncs exactly that branch; otherwise syncs every
    connected branch. Other branches are never touched.
    """
    try:
        return await service.sync_connection(user, db, listing_id=listing_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Localith sync failed: {e}")


@router.get("/connections", response_model=list[ConnectionResponse])
async def list_my_connections(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Every branch this tenant has connected (all listings, all data kept)."""
    connections = await service.list_connections(db, user.id)
    return [_serialize(c) for c in connections]


@router.get("/connection", response_model=ConnectionResponse | None)
async def get_my_connection(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """First connected branch (legacy single-location callers)."""
    c = await service.get_connection(db, user.id)
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
    listing_id: str | None = None,
):
    """Full synced snapshot: profile detail + both metrics summaries.

    With listing_id set, returns exactly that branch; otherwise the first
    connected branch (legacy single-location callers).
    """
    c = await service.get_connection(db, user.id, listing_id)
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
    c = await service.get_connection(db, user.id, body.listing_id)
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
        # Same branch re-saved: refresh display fields only. Other
        # branches are never touched (no more overwrite-the-only-row).
        c.listing_name = body.listing_name
        c.listing_google_id = body.listing_google_id
    await db.commit()
    await db.refresh(c)
    return _serialize(c)


class ApiKeyUpdate(BaseModel):
    api_key: str = Field(..., min_length=8, max_length=512)


@router.put("/connection/api-key", response_model=ConnectionResponse | None)
async def set_connection_api_key(
    body: ApiKeyUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Set (or rotate) this tenant's Localith API key.

    The key is Fernet-encrypted at rest and written to every connection row
    the user owns (the key is account-wide, not per-listing). It overrides
    the shared LOCALITH_API_KEY env for this tenant's syncs and publishes.
    The plaintext is never returned or logged.
    """
    connections = await service.list_connections(db, user.id)
    if not connections:
        raise HTTPException(status_code=400, detail="Connect a Localith listing first.")
    encrypted = _encrypt_localith_key(body.api_key.strip())
    for c in connections:
        c.api_key_encrypted = encrypted
    await db.commit()
    first = connections[0]
    await db.refresh(first)
    return _serialize(first)


@router.delete("/connection/api-key", response_model=ConnectionResponse | None)
async def remove_connection_api_key(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove the tenant's key from every owned connection row; the tenant
    falls back to the shared LOCALITH_API_KEY env."""
    connections = await service.list_connections(db, user.id)
    if not connections:
        raise HTTPException(status_code=400, detail="Connect a Localith listing first.")
    for c in connections:
        c.api_key_encrypted = None
    await db.commit()
    first = connections[0]
    await db.refresh(first)
    return _serialize(first)


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
    listing_id: str | None = None,
):
    """Update the connected listing (writes back to Google via Localith),
    then refresh the stored profile snapshot."""
    import asyncio

    c = await service.get_connection(db, user.id, listing_id)
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
    listing_id: str | None = None,
):
    """Disconnect one branch (its synced artifacts go with it).

    With listing_id set, disconnects exactly that branch. Without it,
    disconnects the only branch — or 400s when several are connected so
    one is never deleted by accident.
    """
    if listing_id:
        c = await service.get_connection(db, user.id, listing_id)
    else:
        connections = await service.list_connections(db, user.id)
        if len(connections) > 1:
            raise HTTPException(
                status_code=400,
                detail="Several branches are connected — specify listing_id.",
            )
        c = connections[0] if connections else None
    if c is None:
        return
    listing_id = c.listing_id
    await db.delete(c)
    await db.flush()

    # Localith-synced artifacts must go with the connection — otherwise the
    # dashboard keeps showing ghost locations, reviews, drafts and stats.
    channels = (
        await db.execute(
            select(Channel).where(
                Channel.user_id == user.id,
                Channel.platform == "google_reviews",
                Channel.metadata_json.contains(listing_id),
            )
        )
    ).scalars().all()
    for ch in channels:
        await db.execute(delete(ReviewReply).where(ReviewReply.channel_id == ch.id))
        await db.execute(delete(ChannelMessage).where(ChannelMessage.channel_id == ch.id))
        await db.execute(delete(AutoReplyConfig).where(AutoReplyConfig.channel_id == ch.id))
        await db.execute(delete(ReviewInsight).where(ReviewInsight.channel_id == ch.id))
        await db.delete(ch)
    await db.execute(
        delete(LocationProfile).where(
            LocationProfile.user_id == user.id,
            LocationProfile.listing_id == listing_id,
        )
    )
    await db.commit()

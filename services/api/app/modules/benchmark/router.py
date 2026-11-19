"""Benchmark API: search Places and manage the tenant's saved bench."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.deps import get_db
from ..team.context import TenantContext, require_perm, tenant_id_of
from . import places, service

router = APIRouter(prefix="/api/v1/benchmark", tags=["benchmark"])


class SavePlaceIn(BaseModel):
    place_id: str = Field(min_length=1, max_length=255)
    label: str | None = Field(default=None, max_length=120)
    notes: str | None = Field(default=None, max_length=2000)


@router.get("/search", response_model=list[dict])
async def search_places(
    q: str = Query(..., min_length=2, max_length=255),
    limit: int = Query(20, ge=1, le=20),
    ctx: TenantContext = Depends(require_perm("benchmark.view")),
    db: AsyncSession = Depends(get_db),
):
    """Search Google Places for businesses. Results are live, not stored."""
    try:
        results = await places.search_places(q)
    except places.PlacesError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc))
    return results[:limit]


@router.get("/places", response_model=list[dict])
async def list_saved(
    limit: int = Query(50, ge=1, le=100),
    ctx: TenantContext = Depends(require_perm("benchmark.view")),
    db: AsyncSession = Depends(get_db),
):
    return await service.list_saved(db, tenant_id_of(ctx.user), limit=limit)


@router.post("/places", response_model=dict, status_code=201)
async def save_place(
    body: SavePlaceIn,
    ctx: TenantContext = Depends(require_perm("benchmark.manage")),
    db: AsyncSession = Depends(get_db),
):
    try:
        row = await service.save_place(
            db, tenant_id_of(ctx.user),
            place_id=body.place_id, label=body.label, notes=body.notes,
        )
    except service.BenchError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return service.serialize(row)


@router.delete("/places/{place_id}", response_model=dict)
async def delete_saved(
    place_id: str,
    ctx: TenantContext = Depends(require_perm("benchmark.manage")),
    db: AsyncSession = Depends(get_db),
):
    removed = await service.delete_saved(db, tenant_id_of(ctx.user), place_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Saved place not found")
    return {"deleted": True, "place_id": place_id}


@router.get("/config", response_model=dict)
async def get_config(
    ctx: TenantContext = Depends(require_perm("benchmark.manage")),
    db: AsyncSession = Depends(get_db),
):
    config = await service.get_config(db)
    return {
        "place_cache_enabled": config.place_cache_enabled,
        "retention_days": config.retention_days,
        "refresh_hours": config.refresh_hours,
        "max_saved_places": config.max_saved_places,
    }

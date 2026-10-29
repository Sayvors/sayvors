"""Catalog CRUD API.

Every query is tenant-scoped from the authenticated context; an item id alone
never grants access.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.deps import get_db
from ..team.context import TenantContext, require_perm
from . import service

router = APIRouter(prefix="/api/v1/catalog", tags=["catalog"])


class CatalogItemIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(None, max_length=4000)
    sku: str | None = Field(None, max_length=80)
    price: float | None = Field(None, ge=0, le=10**9)
    currency: str | None = Field(None, min_length=3, max_length=3)
    image_url: str | None = Field(None, max_length=1000)
    item_url: str | None = Field(None, max_length=1000)
    in_stock: bool = True
    availability_note: str | None = Field(None, max_length=200)
    active: bool = True
    sort_order: int = 0


class CatalogItemPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None, max_length=4000)
    sku: str | None = Field(None, max_length=80)
    price: float | None = Field(None, ge=0, le=10**9)
    currency: str | None = Field(None, min_length=3, max_length=3)
    image_url: str | None = Field(None, max_length=1000)
    item_url: str | None = Field(None, max_length=1000)
    in_stock: bool | None = None
    availability_note: str | None = Field(None, max_length=200)
    active: bool | None = None
    sort_order: int | None = None


class CatalogListResponse(BaseModel):
    items: list[dict]
    total: int


@router.get("", response_model=CatalogListResponse)
async def list_catalog(
    search: str | None = Query(None, max_length=200),
    include_inactive: bool = Query(False),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    ctx: TenantContext = Depends(require_perm("channels.view")),
    db: AsyncSession = Depends(get_db),
) -> CatalogListResponse:
    items, total = await service.list_items(
        db, ctx.tenant_id,
        search=search, include_inactive=include_inactive,
        limit=limit, offset=offset,
    )
    return CatalogListResponse(
        items=[service.serialize_item(item) for item in items], total=total
    )


@router.post("", status_code=status.HTTP_201_CREATED, response_model=dict)
async def create_catalog_item(
    body: CatalogItemIn,
    ctx: TenantContext = Depends(require_perm("channels.edit")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        item = await service.create_item(db, ctx.tenant_id, body.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return service.serialize_item(item)


@router.patch("/{item_id}", response_model=dict)
async def update_catalog_item(
    item_id: str,
    body: CatalogItemPatch,
    ctx: TenantContext = Depends(require_perm("channels.edit")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    item = await service.get_item(db, ctx.tenant_id, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Catalog item not found")
    # exclude_unset so "not provided" never clears a field; explicit null does.
    try:
        item = await service.update_item(db, item, body.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return service.serialize_item(item)


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_catalog_item(
    item_id: str,
    ctx: TenantContext = Depends(require_perm("channels.edit")),
    db: AsyncSession = Depends(get_db),
) -> None:
    item = await service.get_item(db, ctx.tenant_id, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Catalog item not found")
    await service.delete_item(db, item)

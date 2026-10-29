"""Catalog CRUD API and the public share link.

Every query is tenant-scoped from the authenticated context; an item id alone
never grants access. The one unauthenticated route is the public catalog,
where the URL token itself is the credential.
"""
import secrets

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.deps import get_db
from ..team.context import TenantContext, require_perm
from ..users.models import User
from . import service

router = APIRouter(prefix="/api/v1/catalog", tags=["catalog"])

# 24 random bytes -> 32 URL-safe chars. The link is the only credential the
# public page has, so length is the defence against enumeration.
SHARE_TOKEN_BYTES = 24


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


def _share_payload(token: str | None) -> dict:
    return {
        "token": token,
        "path": f"/catalog/{token}" if token else None,
    }


async def _share_row(db, tenant_id: str):
    from .models import CatalogShare

    return (
        await db.execute(
            select(CatalogShare).where(CatalogShare.tenant_id == tenant_id)
        )
    ).scalars().first()


# The share routes are declared before "/{item_id}": FastAPI matches in
# declaration order, and a DELETE on "/share" would otherwise be captured as an
# item id and 404.
@router.get("/share", response_model=dict)
async def get_catalog_share(
    ctx: TenantContext = Depends(require_perm("channels.view")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """The tenant's current public link, or null when none exists."""
    row = await _share_row(db, ctx.tenant_id)
    return _share_payload(row.token if row else None)


@router.post("/share", response_model=dict)
async def create_catalog_share(
    rotate: bool = Query(False),
    ctx: TenantContext = Depends(require_perm("channels.edit")),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Create the public link, or rotate it to kill the old one.

    Rotation is explicit: a customer may have saved the old link, and silently
    replacing it on every click would break them.
    """
    from .models import CatalogShare

    row = await _share_row(db, ctx.tenant_id)
    if row is not None and not rotate:
        return _share_payload(row.token)

    # Retry on the (astronomically unlikely) unique-index collision rather
    # than assuming randomness is enough.
    for _ in range(5):
        token = secrets.token_urlsafe(SHARE_TOKEN_BYTES)
        if row is None:
            db.add(CatalogShare(tenant_id=ctx.tenant_id, token=token))
        else:
            row.token = token
        try:
            await db.commit()
        except Exception:
            await db.rollback()
            continue
        return _share_payload(token)
    raise HTTPException(
        status_code=503, detail="Could not create a catalog link, try again."
    )


@router.delete("/share", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_catalog_share(
    ctx: TenantContext = Depends(require_perm("channels.edit")),
    db: AsyncSession = Depends(get_db),
) -> None:
    row = await _share_row(db, ctx.tenant_id)
    if row is not None:
        await db.delete(row)
        await db.commit()


@router.get("/public/{token}", response_model=dict)
async def public_catalog(token: str, db: AsyncSession = Depends(get_db)) -> dict:
    """The public catalog page's data. No session — the token is the credential.

    Deliberately narrow: names, prices and stock only. Item ids, tenant ids and
    internal flags stay private; the page has no use for them and a public
    payload is a bad place to leak them.
    """
    from .models import CatalogShare

    share = (
        await db.execute(
            select(CatalogShare).where(CatalogShare.token == token)
        )
    ).scalars().first()
    if share is None:
        raise HTTPException(status_code=404, detail="Catalog not found")

    items, _ = await service.list_items(db, share.tenant_id, limit=200)
    owner = await db.get(User, share.tenant_id)
    business = (
        (owner.business_name if owner else None)
        or " ".join(
            part for part in (
                (owner.first_name, owner.last_name) if owner else ()
            ) if part
        ).strip()
        or "Catalog"
    )
    return {
        "business_name": business,
        "items": [
            {
                "name": item.name,
                "description": item.description,
                "price_display": service.price_display(item),
                "image_url": item.image_url,
                "item_url": item.item_url,
                "in_stock": bool(item.in_stock),
                "availability_note": item.availability_note,
            }
            for item in items
        ],
    }


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

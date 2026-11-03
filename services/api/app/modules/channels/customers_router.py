"""Customer (contact) endpoints for the dashboard's "customers" page.

A customer is a thread — the same grouping the inbox already uses — so this
router delegates to `channels.customers_service`, which reuses
`list_inbox_threads` for the grouping and augments it with the lead and
Google review data that already exists.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.deps import get_current_user, get_db
from ..team.context import TenantContext, require_perm
from ..users.models import User
from . import customers_service

router = APIRouter(prefix="/api/v1/customers", tags=["customers"])


@router.get("", response_model=dict)
async def list_customers(
    search: str | None = Query(None, max_length=200),
    platform: str | None = Query(None, max_length=32),
    category: str | None = Query(None, max_length=32),
    priority: str | None = Query(None, max_length=16),
    important: bool | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    cursor: str | None = Query(None, max_length=512),
    sort: str = Query("important", pattern="^(important|recent|messages)$"),
    ctx: TenantContext = Depends(require_perm("inbox.view")),
    db: AsyncSession = Depends(get_db),
):
    """One filtered, RBAC-scoped page of customers.

    Filtering, ordering and pagination happen in SQL; `next_cursor` walks to
    the next page and `total` counts the filtered set.
    """
    try:
        customers, total, next_cursor = await customers_service.list_customers(
            db,
            ctx.user,
            search=search,
            platform=platform,
            category=category,
            priority=priority,
            important=important,
            limit=limit,
            cursor=cursor,
            visible_channel_ids=ctx.visible_channel_ids(),
            sort=sort,
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid cursor") from None
    return {
        "customers": customers,
        "total": total,
        "next_cursor": next_cursor,
    }


@router.get("/{channel_id}/{contact_key}", response_model=dict)
async def get_customer_profile(
    channel_id: str,
    contact_key: str,
    ctx: TenantContext = Depends(require_perm("inbox.view")),
    db: AsyncSession = Depends(get_db),
):
    """The complete profile for one customer."""
    if ctx.channel_level(channel_id) == "none":
        raise HTTPException(status_code=404, detail="Channel not found")
    profile = await customers_service.get_customer_profile(
        db, ctx.user, channel_id, contact_key
    )
    if profile is None:
        raise HTTPException(status_code=404, detail="Customer not found")
    return profile

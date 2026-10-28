"""Customer (contact) endpoints for the dashboard's "customers" page.

A customer is a thread — the same grouping the inbox already uses — so this
router delegates to `channels.customers_service`, which reuses
`list_inbox_threads` for the grouping and augments it with the lead and
Google review data that already exists.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
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
    offset: int = Query(0, ge=0),
    ctx: TenantContext = Depends(require_perm("inbox.view")),
    db: AsyncSession = Depends(get_db),
):
    """List every customer across every channel, newest activity first."""
    from sqlalchemy.ext.asyncio import AsyncSession

    customers, total = await customers_service.list_customers(
        db,
        ctx.user,
        search=search,
        platform=platform,
        category=category,
        priority=priority,
        important=important,
        limit=limit,
        offset=offset,
    )
    visible = ctx.visible_channel_ids()
    if visible is not None:
        customers = [c for c in customers if c.get("channel_id") in visible]
    return {
        "customers": customers,
        "total": len(customers) if visible is not None else total,
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

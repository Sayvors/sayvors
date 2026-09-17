"""Notification center: list, unread count, mark read.

Read model: the header bell polls unread-count; the dropdown and the
detail page read the list. Clicking an item marks it read.
"""
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import desc, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.deps import get_current_user, get_db
from ...config import settings
from ..users.models import User
from .models import Notification

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])

DEMO_USER_ID = getattr(settings, "DEMO_USER_ID", None)


def _uid(user: User) -> str:
    return DEMO_USER_ID if settings.DEMO_MODE else user.id


class NotificationItem(BaseModel):
    id: str
    type: str
    title: str
    body: str | None = None
    data: dict | None = None
    href: str | None = None
    read_at: str | None = None
    created_at: str

    class Config:
        from_attributes = True


class NotificationListResponse(BaseModel):
    total: int
    unread: int
    items: list[NotificationItem]


def _to_item(n: Notification) -> NotificationItem:
    return NotificationItem(
        id=n.id,
        type=n.type,
        title=n.title,
        body=n.body,
        data=n.data or {},
        href=n.href,
        read_at=n.read_at.isoformat() if n.read_at else None,
        created_at=n.created_at.isoformat() if n.created_at else "",
    )


@router.get("", response_model=NotificationListResponse)
async def list_notifications(
    unread_only: bool = Query(False),
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Newest-first notification feed for the dropdown + detail page."""
    uid = _uid(user)
    filt = [Notification.user_id == uid]
    if unread_only:
        filt.append(Notification.read_at.is_(None))
    total = (
        await db.execute(select(func.count(Notification.id)).where(*filt))
    ).scalar_one()
    unread = (
        await db.execute(
            select(func.count(Notification.id)).where(
                Notification.user_id == uid, Notification.read_at.is_(None)
            )
        )
    ).scalar_one()
    rows = (
        await db.execute(
            select(Notification)
            .where(*filt)
            .order_by(desc(Notification.created_at))
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()
    return NotificationListResponse(
        total=total, unread=unread, items=[_to_item(n) for n in rows]
    )


@router.get("/unread-count")
async def unread_count(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Accurate unread badge value for the header bell."""
    uid = _uid(user)
    count = (
        await db.execute(
            select(func.count(Notification.id)).where(
                Notification.user_id == uid, Notification.read_at.is_(None)
            )
        )
    ).scalar_one()
    return {"unread": count}


@router.post("/{notification_id}/read", response_model=NotificationItem)
async def mark_read(
    notification_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark one notification read (dropdown/page item click)."""
    uid = _uid(user)
    row = (
        await db.execute(
            select(Notification).where(
                Notification.id == notification_id, Notification.user_id == uid
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Notification not found")
    if row.read_at is None:
        row.read_at = datetime.now(timezone.utc)
        db.add(row)
        await db.commit()
        await db.refresh(row)
    return _to_item(row)


@router.post("/read-all")
async def mark_all_read(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Mark every notification read."""
    uid = _uid(user)
    result = await db.execute(
        update(Notification)
        .where(Notification.user_id == uid, Notification.read_at.is_(None))
        .values(read_at=datetime.now(timezone.utc))
    )
    await db.commit()
    return {"marked": result.rowcount or 0}

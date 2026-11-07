"""Tenant suspension: one check shared by auth and every request.

Admins suspend a workspace from the admin console. The suspension lives on the
owner row; employees inherit it through `tenant_id`. Keeping the lookup in one
module means login, token refresh, and per-request auth can never disagree
about whether a workspace is active.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import User

DEFAULT_SUSPENSION_MESSAGE = (
    "This workspace is suspended. Contact it@sayvors.com if you believe this is a mistake."
)


async def suspension_message(db: AsyncSession, user: User) -> str | None:
    """The owner-facing reason when the user or their workspace is suspended."""
    if user.suspended_at is not None:
        return user.suspension_reason or DEFAULT_SUSPENSION_MESSAGE
    tenant_id = user.tenant_id
    if tenant_id and tenant_id != user.id:
        row = (
            await db.execute(
                select(User.suspended_at, User.suspension_reason).where(User.id == tenant_id)
            )
        ).first()
        if row is not None and row[0] is not None:
            return row[1] or DEFAULT_SUSPENSION_MESSAGE
    return None

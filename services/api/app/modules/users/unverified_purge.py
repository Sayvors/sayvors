"""Remove never-verified accounts after a grace period, keeping an admin trace.

Unverified signups are not customers yet. Keeping them forever bloats the
users table and gives newsletters/OTP an ever-growing pool of addresses that
were never proven to exist. After `UNVERIFIED_ACCOUNT_TTL_DAYS`, remove the
account and write a `purged_accounts` row with the address, signup time and a
small metadata snapshot.

The trace is deliberately platform-level and survives a tenant purge. It is
visible at Admin -> Operations -> Purged accounts.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from ..admin.models import PurgedAccount
from .models import User

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def purge_unverified_accounts(
    db: AsyncSession, limit: int | None = None
) -> int:
    """Delete a bounded batch of old, never-verified owner accounts."""
    cutoff = _now() - timedelta(days=settings.UNVERIFIED_ACCOUNT_TTL_DAYS)
    batch = max(1, min(int(limit or settings.UNVERIFIED_PURGE_BATCH), 100))
    users = (
        await db.execute(
            select(User)
            .where(
                User.email_verified.is_(False),
                User.created_at < cutoff,
                # Only workspace owners. Employees are invited by an owner and
                # must not be deleted by a signup-hygiene job.
                or_(User.tenant_id.is_(None), User.tenant_id == User.id),
            )
            .order_by(User.created_at)
            .limit(batch)
        )
    ).scalars().all()

    purged = 0
    for user in users:
        archive = await db.get(PurgedAccount, user.id)
        if archive is None:
            archive = PurgedAccount(
                id=user.id,
                email=user.email,
                first_name=user.first_name,
                last_name=user.last_name,
                reason="unverified",
                signed_up_at=user.created_at,
                metadata_json={
                    "business_type": user.business_type,
                    "newsletter": bool(user.newsletter),
                    "plan": user.plan,
                    "has_google": bool(user.google_sub),
                    "has_facebook": bool(user.facebook_id),
                },
            )
            db.add(archive)
        else:
            archive.status = "pending"
            archive.error = None
        archive.purged_at = _now()
        await db.commit()

        try:
            from ..admin.tenant_ops import purge_tenant

            await purge_tenant(db, user.id)
        except Exception as e:  # noqa: BLE001 - record the failure, keep the trace
            await db.rollback()
            archive = await db.get(PurgedAccount, user.id)
            if archive is not None:
                archive.status = "failed"
                archive.error = str(e)[:500]
                await db.commit()
            logger.exception("Unverified account purge failed for %s", user.id)
            continue

        archive = await db.get(PurgedAccount, user.id)
        if archive is not None:
            archive.status = "purged"
            archive.error = None
            await db.commit()
        purged += 1
    return purged


async def run_unverified_purge() -> None:
    """Periodic worker loop; sleeps only when there is no backlog."""
    logger.info("Unverified-account purge worker started")
    from ...database import async_session

    while True:
        try:
            async with async_session() as db:
                purged = await purge_unverified_accounts(db)
            if purged:
                logger.info("Purged %s unverified account(s)", purged)
                continue
            await asyncio.sleep(settings.UNVERIFIED_PURGE_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Unverified-account purge loop failed")
            await asyncio.sleep(settings.UNVERIFIED_PURGE_INTERVAL_SECONDS)

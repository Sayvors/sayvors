"""Who is emailed when a tenant asks for the Enterprise plan.

Sales follows up outside Sayvors (email, call, meeting), so this is the only
configuration that feature needs. The list is platform-level state: operators
own it and edit it from the admin console, one address at a time. Add/remove
instead of a whole-list replace keeps concurrent edits from clobbering each
other and lets the database's unique index arbitrate duplicates.

The cap is enforced on write for a clear error and again on read so a race
between two operators can never make one request mail more than the bound.
"""
from __future__ import annotations

import logging

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..email.outbox import normalize_email
from .models import EnterpriseRequestRecipient

logger = logging.getLogger(__name__)

# Sales lists are small by nature; a bound keeps one tenant request from
# fanning out into an unbounded number of outbox rows.
MAX_RECIPIENTS = 25


class RecipientError(ValueError):
    """A recipient change the operator must fix (bad address, duplicate, cap)."""


def serialize_recipient(row: EnterpriseRequestRecipient) -> dict:
    return {
        "id": row.id,
        "email": row.email,
        "created_by": row.created_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


async def list_recipients(db: AsyncSession) -> list[EnterpriseRequestRecipient]:
    return list(
        (
            await db.execute(
                select(EnterpriseRequestRecipient)
                .order_by(EnterpriseRequestRecipient.created_at)
                .limit(MAX_RECIPIENTS)
            )
        ).scalars().all()
    )


async def recipient_emails(db: AsyncSession) -> list[str]:
    """Addresses to notify, bounded even if the write-side cap was raced."""
    return list(
        (
            await db.execute(
                select(EnterpriseRequestRecipient.email)
                .order_by(EnterpriseRequestRecipient.created_at)
                .limit(MAX_RECIPIENTS)
            )
        ).scalars().all()
    )


async def add_recipient(
    db: AsyncSession, *, email: str, operator: str | None
) -> EnterpriseRequestRecipient:
    normalized = normalize_email(email)
    if not normalized:
        raise RecipientError("Enter a valid email address.")

    count = (
        await db.execute(select(func.count()).select_from(EnterpriseRequestRecipient))
    ).scalar_one()
    if count >= MAX_RECIPIENTS:
        raise RecipientError(
            f"The notification list is limited to {MAX_RECIPIENTS} addresses."
        )

    row = EnterpriseRequestRecipient(
        email=normalized,
        created_by=(operator or "").strip()[:64] or None,
    )
    db.add(row)
    try:
        await db.commit()
    except IntegrityError:
        # The unique index is the arbiter; a concurrent add of the same
        # address means the operator's intent is already satisfied.
        await db.rollback()
        raise RecipientError("That address is already on the list.") from None
    await db.refresh(row)
    logger.info("Enterprise recipient added by %s", operator or "admin")
    return row


async def remove_recipient(db: AsyncSession, recipient_id: str) -> bool:
    result = await db.execute(
        delete(EnterpriseRequestRecipient).where(
            EnterpriseRequestRecipient.id == recipient_id
        )
    )
    await db.commit()
    removed = bool(result.rowcount)
    if removed:
        logger.info("Enterprise recipient removed id=%s", recipient_id)
    return removed

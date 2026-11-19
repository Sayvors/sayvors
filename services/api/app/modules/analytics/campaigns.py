"""Review Campaign service: plan-limited, time-boxed review asks.

A campaign is a planning + results record. The individual sends remain
ReviewRequest rows linked by campaign_id, so delivery, click tracking and
review attribution are the same machinery the rest of the product uses.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy import Integer, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..billing.entitlements import get_entitlements
from .models import ReviewCampaign, ReviewRequest

logger = logging.getLogger(__name__)

MAX_NAME = 120
MAX_TEMPLATE = 8000
MAX_LIST = 100


class CampaignError(ValueError):
    """A validation or plan-limit failure safe to show to the tenant."""


def campaign_status(campaign: ReviewCampaign, *, today: date | None = None) -> str:
    """Stored status is only terminal for cancellations; dates decide the rest."""
    if campaign.status == "cancelled":
        return "cancelled"
    today = today or datetime.now(timezone.utc).date()
    start = campaign.from_date
    end = campaign.to_date
    if isinstance(start, datetime):
        start = start.date()
    if isinstance(end, datetime):
        end = end.date()
    if today < start:
        return "scheduled"
    if today > end:
        return "ended"
    return "active"


def _month_start(now: datetime) -> datetime:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def _check_limits(db: AsyncSession, tenant_id: str, days: int) -> None:
    ent = await get_entitlements(tenant_id, db)
    if not ent.campaign_days_ok(days):
        limit = ent.max_campaign_days
        raise CampaignError(f"This plan allows campaigns of up to {limit} days.")
    used = (
        await db.execute(
            select(func.count(ReviewCampaign.id)).where(
                ReviewCampaign.tenant_id == tenant_id,
                ReviewCampaign.created_at >= _month_start(datetime.now(timezone.utc)),
            )
        )
    ).scalar() or 0
    if not ent.campaign_quota_ok(int(used)):
        raise CampaignError(
            f"This plan allows {ent.max_campaigns_per_month} campaigns per month."
        )


def _validate(
    *, name: str, from_date: date, to_date: date, message_template: str | None
) -> tuple[str, date, date, str | None]:
    name = (name or "").strip()[:MAX_NAME]
    if not name:
        raise CampaignError("Give the campaign a name.")
    if not isinstance(from_date, date) or not isinstance(to_date, date):
        raise CampaignError("Choose a valid start and end date.")
    if to_date < from_date:
        raise CampaignError("The end date must be on or after the start date.")
    days = (to_date - from_date).days + 1
    template = (message_template or "").strip()[:MAX_TEMPLATE] or None
    if template and "{link}" not in template:
        raise CampaignError("The message must include {link} so customers can leave a review.")
    return name, from_date, to_date, template


def serialize(campaign: ReviewCampaign, *, today: date | None = None) -> dict[str, Any]:
    return {
        "id": campaign.id,
        "tenant_id": campaign.tenant_id,
        "name": campaign.name,
        "from_date": campaign.from_date.isoformat() if isinstance(campaign.from_date, date) else str(campaign.from_date),
        "to_date": campaign.to_date.isoformat() if isinstance(campaign.to_date, date) else str(campaign.to_date),
        "status": campaign_status(campaign, today=today),
        "message_template": campaign.message_template,
        "channel_id": campaign.channel_id,
        "duplicated_from": campaign.duplicated_from,
        "recipient_count": campaign.recipient_count,
        "sent_count": campaign.sent_count,
        "clicked_count": campaign.clicked_count,
        "reviewed_count": campaign.reviewed_count,
        "conversion_rate": (
            round(campaign.reviewed_count / campaign.recipient_count * 100, 1)
            if campaign.recipient_count else None
        ),
        "created_at": campaign.created_at.isoformat() if campaign.created_at else None,
    }


async def create_campaign(
    db: AsyncSession,
    *,
    tenant_id: str,
    name: str,
    from_date: date,
    to_date: date,
    message_template: str | None = None,
    channel_id: str | None = None,
    duplicated_from: str | None = None,
) -> ReviewCampaign:
    name, from_date, to_date, template = _validate(
        name=name, from_date=from_date, to_date=to_date, message_template=message_template
    )
    days = (to_date - from_date).days + 1
    await _check_limits(db, tenant_id, days)

    row = ReviewCampaign(
        tenant_id=tenant_id, name=name, from_date=from_date, to_date=to_date,
        status=campaign_status(ReviewCampaign(
            tenant_id=tenant_id, from_date=from_date, to_date=to_date, status="scheduled"
        )),
        message_template=template, channel_id=channel_id or None,
        duplicated_from=duplicated_from,
    )
    db.add(row)
    try:
        await db.commit()
    except IntegrityError as exc:  # noqa: BLE001
        await db.rollback()
        raise CampaignError("Could not create the campaign.") from exc
    await db.refresh(row)
    return row


async def list_campaigns(db: AsyncSession, tenant_id: str, *, limit: int = MAX_LIST) -> list[dict[str, Any]]:
    rows = (
        await db.execute(
            select(ReviewCampaign)
            .where(ReviewCampaign.tenant_id == tenant_id)
            .order_by(ReviewCampaign.from_date.desc())
            .limit(max(1, min(int(limit), MAX_LIST)))
        )
    ).scalars().all()
    today = datetime.now(timezone.utc).date()
    return [serialize(row, today=today) for row in rows]


async def duplicate_campaign(
    db: AsyncSession, tenant_id: str, campaign_id: str
) -> ReviewCampaign:
    """Reuse the copy and window length for a fresh, empty upcoming campaign."""
    source = (
        await db.execute(
            select(ReviewCampaign).where(
                ReviewCampaign.id == campaign_id,
                ReviewCampaign.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if source is None:
        raise CampaignError("Campaign not found.")
    length = (source.to_date - source.from_date).days + 1
    start = datetime.now(timezone.utc).date() + timedelta(days=1)
    return await create_campaign(
        db, tenant_id=tenant_id,
        name=f"{source.name} (copy)",
        from_date=start, to_date=start + timedelta(days=length - 1),
        message_template=source.message_template,
        channel_id=source.channel_id,
        duplicated_from=source.id,
    )


async def cancel_campaign(db: AsyncSession, tenant_id: str, campaign_id: str) -> ReviewCampaign:
    row = (
        await db.execute(
            select(ReviewCampaign).where(
                ReviewCampaign.id == campaign_id,
                ReviewCampaign.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise CampaignError("Campaign not found.")
    if campaign_status(row) == "cancelled":
        return row
    if campaign_status(row) == "ended":
        raise CampaignError("An ended campaign cannot be cancelled.")
    row.status = "cancelled"
    await db.commit()
    await db.refresh(row)
    return row


async def refresh_results(db: AsyncSession, tenant_id: str, campaign_id: str) -> ReviewCampaign:
    """Recompute the four counters from ReviewRequest rows (idempotent)."""
    row = (
        await db.execute(
            select(ReviewCampaign).where(
                ReviewCampaign.id == campaign_id,
                ReviewCampaign.tenant_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise CampaignError("Campaign not found.")
    counts = (
        await db.execute(
            select(
                func.count(ReviewRequest.id),
                func.sum(func.cast(ReviewRequest.clicked_at.is_not(None), Integer)),
                func.sum(func.cast(ReviewRequest.reviewed_at.is_not(None), Integer)),
            ).where(ReviewRequest.campaign_id == campaign_id)
        )
    ).one()
    row.recipient_count = int(counts[0] or 0)
    row.sent_count = int(counts[0] or 0)
    row.clicked_count = int(counts[1] or 0)
    row.reviewed_count = int(counts[2] or 0)
    await db.commit()
    await db.refresh(row)
    return row

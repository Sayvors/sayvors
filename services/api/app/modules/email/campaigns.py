"""Newsletter campaigns: compose once, expand into the durable outbox in batches.

The API never sends a campaign directly. A campaign snapshots the eligible
audience at start (`max_user_id`), then a worker walks that snapshot with a
keyset cursor (`last_user_id`) and enqueues one `email_outbox` row per
recipient. The outbox worker owns delivery, retries and suppression, so the
campaign layer only has to be resumable and idempotent.

Idempotency: the outbox key is `campaign:{campaign_id}:{user_id}`. A crash
between enqueue and cursor advance re-walks the same batch and the key returns
the existing row instead of sending twice.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from html import escape

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from ..users.models import User
from . import templates
from .models import EmailCampaign, EmailOutbox
from .outbox import enqueue_email, marketing_headers, normalize_email
from .schemas import CampaignCreateIn
from .service import SUPPORT_EMAIL

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _audience_conditions():
    """Recipients eligible for a platform newsletter.

    Only verified addresses that still carry newsletter consent. Suppression
    is checked again at enqueue time because it can change mid-campaign.
    """
    return (
        User.newsletter.is_(True),
        User.email_verified.is_(True),
        User.email.isnot(None),
    )


async def count_audience(db: AsyncSession, *, max_user_id: str | None = None) -> int:
    conditions = list(_audience_conditions())
    if max_user_id:
        conditions.append(User.id <= max_user_id)
    result = await db.execute(
        select(func.count()).select_from(User).where(*conditions)
    )
    return int(result.scalar() or 0)


async def create_campaign(
    db: AsyncSession,
    *,
    created_by: str | None,
    body: CampaignCreateIn,
) -> EmailCampaign:
    campaign = EmailCampaign(
        created_by=created_by,
        subject=body.subject.strip(),
        html=body.html,
        text=body.text,
        batch_size=body.batch_size,
        interval_seconds=body.interval_seconds,
        status="draft",
    )
    db.add(campaign)
    await db.commit()
    await db.refresh(campaign)
    return campaign


async def start_campaign(db: AsyncSession, campaign: EmailCampaign) -> None:
    """Snapshot the audience and hand the campaign to the expansion worker."""
    max_user_id = (
        await db.execute(
            select(func.max(User.id)).where(*_audience_conditions())
        )
    ).scalar_one_or_none()
    total = await count_audience(db, max_user_id=max_user_id) if max_user_id else 0
    now = _now()
    campaign.max_user_id = max_user_id
    campaign.last_user_id = None
    campaign.total_recipients = total
    campaign.expanded_recipients = 0
    campaign.started_at = now
    campaign.error = None
    if total == 0:
        campaign.status = "completed"
        campaign.completed_at = now
        campaign.next_expand_at = None
    else:
        campaign.status = "running"
        campaign.next_expand_at = now
    await db.commit()
    await db.refresh(campaign)


def cancel_campaign(campaign: EmailCampaign) -> None:
    """Stop future expansion. Rows already queued still deliver."""
    if campaign.status in ("draft", "running"):
        campaign.status = "cancelled"
        campaign.cancelled_at = _now()
        campaign.next_expand_at = None


def _render(value: str | None, user: User) -> str | None:
    if not value:
        return value
    # The body is admin-authored HTML; only the substituted values are user
    # data, so escape those and leave the template markup alone.
    return value.replace("{name}", escape(user.first_name or "there")).replace(
        "{email}", escape(user.email or "")
    )


async def expand_one(db: AsyncSession, campaign: EmailCampaign) -> int:
    """Enqueue one batch of recipients and advance the cursor. Returns users walked."""
    conditions = list(_audience_conditions())
    conditions.append(User.id > (campaign.last_user_id or ""))
    if campaign.max_user_id:
        conditions.append(User.id <= campaign.max_user_id)
    users = (
        await db.execute(
            select(User)
            .where(*conditions)
            .order_by(User.id)
            .limit(campaign.batch_size)
        )
    ).scalars().all()

    now = _now()
    if not users:
        campaign.status = "completed"
        campaign.completed_at = now
        campaign.next_expand_at = None
        await db.commit()
        return 0

    frontend_url = (settings.FRONTEND_URL or "https://sayvors.com").rstrip("/")

    for user in users:
        email = normalize_email(user.email)
        if not email:
            continue
        html = templates.newsletter_email(
            subject=campaign.subject,
            body_html=_render(campaign.html, user) or "",
            frontend_url=frontend_url,
            support_email=SUPPORT_EMAIL,
            help_url=f"{frontend_url}/dashboard",
            privacy_url=f"{frontend_url}/privacy",
        )
        await enqueue_email(
            db,
            to=email,
            subject=campaign.subject,
            html=html,
            text=_render(campaign.text, user),
            kind="newsletter",
            tenant_id=user.id,
            idempotency_key=f"campaign:{campaign.id}:{user.id}",
            headers=marketing_headers(email),
            campaign_id=campaign.id,
        )

    campaign.last_user_id = users[-1].id
    campaign.expanded_recipients = (campaign.expanded_recipients or 0) + len(users)
    if campaign.expanded_recipients >= campaign.total_recipients:
        campaign.status = "completed"
        campaign.completed_at = now
        campaign.next_expand_at = None
    else:
        campaign.next_expand_at = now + timedelta(seconds=campaign.interval_seconds)
    await db.commit()
    return len(users)


async def expand_due_campaigns(limit: int = 5) -> int:
    """Lease due running campaigns and expand one batch each."""
    from ...database import async_session

    async with async_session() as db:
        now = _now()
        ids = (
            await db.execute(
                select(EmailCampaign.id)
                .where(
                    EmailCampaign.status == "running",
                    EmailCampaign.next_expand_at.is_not(None),
                    EmailCampaign.next_expand_at <= now,
                )
                .order_by(EmailCampaign.next_expand_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).scalars().all()
        if not ids:
            return 0
        # Lease before releasing the row locks: enqueue_email commits per row,
        # which would drop a row lock and let a second worker in.
        lease = now + timedelta(
            seconds=max(300, settings.EMAIL_CAMPAIGN_INTERVAL_SECONDS)
        )
        await db.execute(
            update(EmailCampaign)
            .where(EmailCampaign.id.in_(ids))
            .values(next_expand_at=lease)
        )
        await db.commit()

        walked = 0
        for campaign_id in ids:
            campaign = await db.get(EmailCampaign, campaign_id)
            if campaign is None or campaign.status != "running":
                continue
            try:
                walked += await expand_one(db, campaign)
            except Exception as e:  # noqa: BLE001 - one campaign must not stop the rest
                await db.rollback()
                campaign = await db.get(EmailCampaign, campaign_id)
                if campaign is not None:
                    campaign.error = str(e)[:500]
                    campaign.next_expand_at = now + timedelta(
                        seconds=max(300, campaign.interval_seconds)
                    )
                    await db.commit()
                logger.exception("Campaign %s expansion failed", campaign_id)
        return walked


async def run_campaign_worker() -> None:
    logger.info("Email campaign worker started")
    while True:
        try:
            walked = await expand_due_campaigns()
            if not walked:
                await asyncio.sleep(settings.EMAIL_CAMPAIGN_POLL_SECONDS)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Email campaign loop failed")
            await asyncio.sleep(settings.EMAIL_CAMPAIGN_POLL_SECONDS)


async def campaign_out(db: AsyncSession, campaign: EmailCampaign) -> dict:
    counts = dict(
        (
            await db.execute(
                select(EmailOutbox.status, func.count())
                .where(EmailOutbox.campaign_id == campaign.id)
                .group_by(EmailOutbox.status)
            )
        ).all()
    )
    return {
        "id": campaign.id,
        "subject": campaign.subject,
        "status": campaign.status,
        "created_by": campaign.created_by,
        "total_recipients": campaign.total_recipients,
        "expanded_recipients": campaign.expanded_recipients,
        "queued": counts.get("queued", 0) + counts.get("sending", 0),
        "sent": counts.get("sent", 0),
        "failed": counts.get("failed", 0),
        "dead": counts.get("dead", 0),
        "suppressed": counts.get("suppressed", 0),
        "batch_size": campaign.batch_size,
        "interval_seconds": campaign.interval_seconds,
        "error": campaign.error,
        "created_at": campaign.created_at.isoformat() if campaign.created_at else None,
        "started_at": campaign.started_at.isoformat() if campaign.started_at else None,
        "completed_at": campaign.completed_at.isoformat() if campaign.completed_at else None,
        "cancelled_at": campaign.cancelled_at.isoformat() if campaign.cancelled_at else None,
    }

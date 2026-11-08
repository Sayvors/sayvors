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
import math
import re
from datetime import datetime, timedelta, timezone
from html import escape

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from ..analytics.models import ReviewInsight
from ..users.models import User
from . import templates
from .models import EmailCampaign, EmailEvent, EmailOutbox, EmailSuppression
from .outbox import enqueue_email, marketing_headers, normalize_email, unsubscribe_url
from .schemas import CampaignCreateIn, CampaignPreviewIn
from .service import SUPPORT_EMAIL

logger = logging.getLogger(__name__)

_VAR_RE = re.compile(r"\{([a-z][a-z0-9_]*)\}")

# Variables exposed to the composer. tenant_id is deliberately absent: it is
# an internal join key, never shown to the admin or the recipient.
CAMPAIGN_VARIABLES = [
    {"key": "name", "label": "First name", "example": "Saeed"},
    {"key": "email", "label": "Recipient email", "example": "saeed@example.com"},
    {"key": "tenant_name", "label": "Workspace / owner name", "example": "Saeed"},
    {"key": "tenant_total_reviews", "label": "Total Google reviews", "example": "128"},
    {"key": "tenant_avg_rating", "label": "Average rating", "example": "4.7"},
    {"key": "tenant_plan", "label": "Plan", "example": "free-trial"},
    {
        "key": "tenant_free_trial_days_left",
        "label": "Free-trial days left",
        "example": "9",
    },
    {
        "key": "dashboard_url",
        "label": "Dashboard link",
        "example": "https://app.sayvors.com/dashboard",
    },
    # The visible unsubscribe link is injected into the shared footer by
    # `newsletter_email`, so it is not offered as a body variable.
    # Convenience aliases matching the wording admins naturally use.
    {"key": "reviews", "label": "Total reviews (alias)", "example": "128"},
    {"key": "avg_rating", "label": "Average rating (alias)", "example": "4.7"},
]

# Ready-made bodies for the composer. Every variable here is resolved per
# recipient; the unsubscribe link lives in the shared footer.
CAMPAIGN_PRESETS = [
    {
        "id": "weekly-update",
        "name": "Weekly update",
        "description": "Weekend review summary with dashboard and blog links.",
        "subject": "Your weekly review update from Sayvors",
        "body_html": (
            "<h2>Hi {name},</h2>"
            "<p>This weekend your workspace collected "
            "<strong>{reviews} reviews</strong> with an average rating of "
            "<strong>{avg_rating}</strong>.</p>"
            "<p><a href=\"{dashboard_url}\">Open your dashboard</a> to see them "
            "and reply where needed.</p>"
            "<p>Read more on our <a href=\"https://sayvors.com/blog\">blog</a>.</p>"
        ),
    },
    {
        "id": "monthly-newsletter",
        "name": "Monthly newsletter",
        "description": "Month-in-review with the tenant’s rating and plan.",
        "subject": "Your monthly Sayvors update",
        "body_html": (
            "<h2>Hi {name},</h2>"
            "<p>Here is your monthly snapshot: <strong>{reviews} reviews</strong> "
            "and an average rating of <strong>{avg_rating}</strong>.</p>"
            "<p>You are on the <strong>{tenant_plan}</strong> plan. "
            "<a href=\"{dashboard_url}\">Open your dashboard</a> to review "
            "performance and plan next month.</p>"
            "<h3>From the blog</h3>"
            "<ul><li><a href=\"https://sayvors.com/blog\">What changed this month</a></li>"
            "<li><a href=\"https://sayvors.com/blog\">A practical review checklist</a></li></ul>"
        ),
    },
    {
        "id": "product-announcement",
        "name": "Product announcement",
        "description": "Short feature announcement with a dashboard CTA.",
        "subject": "New in Sayvors",
        "body_html": (
            "<h2>Hi {name},</h2>"
            "<p>We shipped something new for your workspace.</p>"
            "<ul><li>Faster review insights</li><li>Cleaner inbox controls</li>"
            "<li>More reliable WhatsApp replies</li></ul>"
            "<p><a href=\"{dashboard_url}\">See it in your dashboard</a>.</p>"
        ),
    },
    {
        "id": "trial-reminder",
        "name": "Trial reminder",
        "description": "Trial days left with a dashboard/upgrade CTA.",
        "subject": "You have {tenant_free_trial_days_left} days left on your trial",
        "body_html": (
            "<h2>Hi {name},</h2>"
            "<p>Your free trial has <strong>{tenant_free_trial_days_left} days</strong> "
            "left.</p>"
            "<p>You have collected <strong>{reviews} reviews</strong> with an average "
            "rating of <strong>{avg_rating}</strong> so far.</p>"
            "<p><a href=\"{dashboard_url}\">Open your dashboard</a> to keep everything "
            "running.</p>"
        ),
    },
]


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


async def list_audience(
    db: AsyncSession, *, limit: int = 50, offset: int = 0
) -> list[dict]:
    """Preview exactly who the campaign would target, with addresses.

    Admins need to verify the audience before a send, not just see a count.
    `suppressed` marks an address that consent allows but delivery will skip.
    """
    suppressed = (
        select(EmailSuppression.email)
        .where(EmailSuppression.email == User.email)
        .exists()
    )
    rows = (
        await db.execute(
            select(User, suppressed.label("suppressed"))
            .where(*_audience_conditions())
            .order_by(User.id)
            .limit(limit)
            .offset(offset)
        )
    ).all()
    return [
        {
            "id": user.id,
            # Employees act inside their owner's workspace; link there.
            "tenant_id": user.tenant_id or user.id,
            "email": user.email,
            "first_name": user.first_name,
            "suppressed": bool(is_suppressed),
        }
        for user, is_suppressed in rows
    ]


async def create_campaign(
    db: AsyncSession,
    *,
    created_by: str | None,
    body: CampaignCreateIn,
) -> EmailCampaign:
    campaign = EmailCampaign(
        created_by=created_by,
        name=((body.name or body.subject).strip()[:120]),
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


async def cancel_campaign(db: AsyncSession, campaign: EmailCampaign) -> None:
    """Stop the campaign and cancel every outbox row that has not started sending.

    A row already in `sending` may still reach Resend; the provider call is
    already in flight. Everything still `queued` is marked `cancelled` so a
    cancel actually stops the remaining mail instead of only stopping future
    batches.
    """
    if campaign.status not in ("draft", "running"):
        return
    campaign.status = "cancelled"
    campaign.cancelled_at = _now()
    campaign.next_expand_at = None
    await db.execute(
        update(EmailOutbox)
        .where(
            EmailOutbox.campaign_id == campaign.id,
            EmailOutbox.status == "queued",
        )
        .values(status="cancelled", error="Campaign cancelled")
    )
    await db.commit()


def _format_avg(value) -> str:
    return f"{float(value):.1f}" if value is not None else "—"


async def build_variable_contexts(
    db: AsyncSession, users: list[User]
) -> dict[str, dict[str, dict[str, str]]]:
    """Resolve campaign variables for a batch of recipients.

    One aggregate query for reviews covers the whole batch; trial days come
    from the user row. Returns both an HTML-escaped map (for the body) and a
    raw map (for the subject/plain text).
    """
    ids = [user.id for user in users]
    review_stats: dict[str, tuple[int, float | None]] = {}
    if ids:
        rows = (
            await db.execute(
                select(
                    ReviewInsight.user_id,
                    func.count(),
                    func.avg(ReviewInsight.rating),
                )
                .where(ReviewInsight.user_id.in_(ids))
                .group_by(ReviewInsight.user_id)
            )
        ).all()
        review_stats = {
            user_id: (int(count), avg) for user_id, count, avg in rows
        }

    now = _now()
    base = (settings.FRONTEND_URL or "https://sayvors.com").rstrip("/")
    contexts: dict[str, dict[str, dict[str, str]]] = {}
    for user in users:
        count, avg = review_stats.get(user.id, (0, None))
        trial_left = ""
        if user.plan == "free-trial" and user.created_at:
            created = user.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            end = created + timedelta(days=settings.FREE_TRIAL_DAYS)
            days = math.ceil(max(0.0, (end - now).total_seconds()) / 86400)
            trial_left = str(days)
        raw = {
            "name": user.first_name or "there",
            "email": user.email or "",
            "tenant_name": user.first_name or "there",
            "tenant_total_reviews": str(count),
            "tenant_avg_rating": _format_avg(avg),
            "tenant_plan": user.plan or "",
            "tenant_free_trial_days_left": trial_left,
            "reviews": str(count),
            "avg_rating": _format_avg(avg),
            "dashboard_url": f"{base}/dashboard",
            "unsubscribe_url": unsubscribe_url(user.email or ""),
        }
        contexts[user.id] = {
            "html": {key: escape(value, quote=True) for key, value in raw.items()},
            "text": raw,
        }
    return contexts


def render_campaign_text(
    value: str | None, context: dict[str, dict[str, str]], *, html: bool
) -> str | None:
    """Replace `{variable}` tokens, leaving unknown tokens visible."""
    if not value:
        return value
    values = context["html" if html else "text"]

    def _replace(match: re.Match[str]) -> str:
        return values.get(match.group(1), match.group(0))

    return _VAR_RE.sub(_replace, value)


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
    contexts = await build_variable_contexts(db, users)

    for user in users:
        email = normalize_email(user.email)
        if not email:
            continue
        context = contexts[user.id]
        rendered_subject = (
            render_campaign_text(campaign.subject, context, html=False)
            or campaign.subject
        )
        html = templates.newsletter_email(
            subject=rendered_subject,
            body_html=render_campaign_text(campaign.html, context, html=True) or "",
            frontend_url=frontend_url,
            support_email=SUPPORT_EMAIL,
            help_url=f"{frontend_url}/dashboard",
            privacy_url=f"{frontend_url}/privacy",
            unsubscribe_url=unsubscribe_url(email),
        )
        await enqueue_email(
            db,
            to=email,
            subject=rendered_subject,
            html=html,
            text=render_campaign_text(campaign.text, context, html=False),
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


async def list_campaign_recipients(
    db: AsyncSession,
    campaign_id: str,
    *,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Per-recipient delivery rows for one campaign, newest first.

    The admin needs the address and the delivery error, not just aggregate
    counts, so this is the outbox row itself rather than a second projection.
    """
    conditions = [EmailOutbox.campaign_id == campaign_id]
    if status:
        conditions.append(EmailOutbox.status == status)
    total = int(
        (
            await db.execute(
                select(func.count()).select_from(EmailOutbox).where(*conditions)
            )
        ).scalar()
        or 0
    )
    rows = (
        await db.execute(
            select(EmailOutbox)
            .where(*conditions)
            .order_by(EmailOutbox.created_at.desc(), EmailOutbox.id)
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()
    counts = dict(
        (
            await db.execute(
                select(EmailOutbox.status, func.count())
                .where(EmailOutbox.campaign_id == campaign_id)
                .group_by(EmailOutbox.status)
            )
        ).all()
    )
    # "sent" only means Resend accepted the request. Surface the latest
    # provider event so a later bounce/complaint is visible against the address.
    latest: dict[str, EmailEvent] = {}
    tenant_links: dict[str, str] = {}
    if rows:
        events = (
            await db.execute(
                select(EmailEvent)
                .where(EmailEvent.outbox_id.in_([row.id for row in rows]))
                .order_by(EmailEvent.created_at.desc())
            )
        ).scalars().all()
        for event in events:
            latest.setdefault(event.outbox_id, event)
        user_ids = [row.tenant_id for row in rows if row.tenant_id]
        if user_ids:
            user_rows = (
                await db.execute(
                    select(User.id, User.tenant_id).where(User.id.in_(user_ids))
                )
            ).all()
            tenant_links = {
                user_id: (tenant_id or user_id)
                for user_id, tenant_id in user_rows
            }
    return {
        "items": [
            {
                "id": row.id,
                "tenant_id": tenant_links.get(row.tenant_id or "", row.tenant_id),
                "email": row.to_email,
                "status": row.status,
                "attempts": row.attempts,
                "error": row.error,
                "last_event": latest[row.id].type if row.id in latest else None,
                "last_event_detail": latest[row.id].detail if row.id in latest else None,
                "last_event_at": (
                    latest[row.id].created_at.isoformat()
                    if row.id in latest and latest[row.id].created_at
                    else None
                ),
                "created_at": row.created_at.isoformat() if row.created_at else None,
                "sent_at": row.sent_at.isoformat() if row.sent_at else None,
            }
            for row in rows
        ],
        "total": total,
        "counts": counts,
    }


async def preview_campaign(
    db: AsyncSession, body: CampaignPreviewIn
) -> dict:
    """Render the composer against a real eligible tenant."""
    user = None
    if body.tenant_id:
        user = await db.get(User, body.tenant_id)
    if user is None:
        user = (
            await db.execute(
                select(User)
                .where(*_audience_conditions())
                .order_by(User.id)
                .limit(1)
            )
        ).scalar_one_or_none()
    if user is None:
        raise ValueError("No eligible recipient to preview.")

    contexts = await build_variable_contexts(db, [user])
    context = contexts[user.id]
    subject = render_campaign_text(body.subject, context, html=False) or body.subject
    body_html = render_campaign_text(body.html, context, html=True) or ""
    text = render_campaign_text(body.text, context, html=False)
    frontend_url = (settings.FRONTEND_URL or "https://sayvors.com").rstrip("/")
    html = templates.newsletter_email(
        subject=subject,
        body_html=body_html,
        frontend_url=frontend_url,
        support_email=SUPPORT_EMAIL,
        help_url=f"{frontend_url}/dashboard",
        privacy_url=f"{frontend_url}/privacy",
        unsubscribe_url=unsubscribe_url(user.email or ""),
    )
    return {
        "tenant": {"name": user.first_name, "email": user.email},
        "subject": subject,
        "body_html": body_html,
        "text": text,
        "html": html,
    }


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
        "name": campaign.name or campaign.subject,
        "subject": campaign.subject,
        "status": campaign.status,
        "created_by": campaign.created_by,
        "total_recipients": campaign.total_recipients,
        "expanded_recipients": campaign.expanded_recipients,
        "queued": counts.get("queued", 0) + counts.get("sending", 0),
        "sent": counts.get("sent", 0),
        "failed": counts.get("failed", 0),
        "dead": counts.get("dead", 0),
        "cancelled": counts.get("cancelled", 0),
        "suppressed": counts.get("suppressed", 0),
        "batch_size": campaign.batch_size,
        "interval_seconds": campaign.interval_seconds,
        "error": campaign.error,
        "created_at": campaign.created_at.isoformat() if campaign.created_at else None,
        "started_at": campaign.started_at.isoformat() if campaign.started_at else None,
        "completed_at": campaign.completed_at.isoformat() if campaign.completed_at else None,
        "cancelled_at": campaign.cancelled_at.isoformat() if campaign.cancelled_at else None,
    }

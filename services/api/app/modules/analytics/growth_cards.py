"""Growth cards: the review-request funnel, new contacts, ask timing, and
recommended actions.

The funnel is cohort-shaped: requests sent in the window are the denominator,
reviews received in the same window are the numerator. That is not perfect
attribution (a review can land outside the window), so the UI labels it as a
window funnel rather than claiming per-request causality.

Delivery/click stages are only shown as tracked when the channel records them;
otherwise they are explicit ``null`` and the UI says "not tracked", never a
fabricated 100%.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..channels.models import Channel
from .models import ChannelDailyMetric, ReviewInsight, ReviewRequest

logger = logging.getLogger(__name__)

MAX_ACTIONS = 4


def _bucket():
    return func.coalesce(ReviewInsight.review_updated_at, ReviewInsight.created_at)


def _pct(part: int, whole: int) -> float | None:
    return round((part / whole) * 100.0, 1) if whole else None


async def get_growth_cards(
    db: AsyncSession,
    user_id: str,
    channel_id: str | None = None,
    days: int = 30,
) -> dict:
    now = datetime.now(timezone.utc)
    start = now - timedelta(days=days)
    prev_start = start - timedelta(days=days)

    empty = ReviewInsight.user_id == user_id
    base = [empty, ReviewInsight.removed_at.is_(None), ReviewInsight.skipped.is_(False)]
    if channel_id:
        base.append(ReviewInsight.channel_id == channel_id)
    bucket = _bucket()

    # ── Review-request funnel ─────────────────────────────────────────────
    req_filters = [ReviewRequest.user_id == user_id, ReviewRequest.sent_at >= start, ReviewRequest.sent_at < now]
    if channel_id:
        req_filters.append(ReviewRequest.channel_id == channel_id)
    req_row = (
        await db.execute(
            select(
                func.count(),
                func.sum(case((ReviewRequest.clicked_at.isnot(None), 1), else_=0)),
                func.sum(case((ReviewRequest.status == "failed", 1), else_=0)),
            ).where(*req_filters)
        )
    ).one()
    requests_sent = int(req_row[0] or 0)
    clicked = int(req_row[1] or 0)
    failed = int(req_row[2] or 0)
    delivered = int(
        (
            await db.execute(
                select(func.count()).where(
                    *req_filters,
                    ReviewRequest.sent_via.in_(("sms", "email")),
                    ReviewRequest.status != "failed",
                )
            )
        ).scalar()
        or 0
    )

    # Per-request attribution: a review is credited to a click within the
    # attribution window, at most one review per click. This replaces the old
    # "window reviews / window requests" ratio, which credited reviews that
    # had nothing to do with a request.
    clicked_reqs = (
        await db.execute(
            select(ReviewRequest.clicked_at).where(*req_filters, ReviewRequest.clicked_at.isnot(None))
        )
    ).scalars().all()
    review_rows = (
        await db.execute(
            select(ReviewInsight.review_updated_at, ReviewInsight.created_at).where(
                *base, bucket >= start, bucket < now
            )
        )
    ).all()

    from .review_requests import ATTRIBUTION_WINDOW_DAYS, attribute_reviews

    attributed = attribute_reviews(
        list(clicked_reqs),
        [updated or created for updated, created in review_rows],
        ATTRIBUTION_WINDOW_DAYS,
    )

    review_row = (
        await db.execute(
            select(func.count(), func.avg(ReviewInsight.rating)).where(*base, bucket >= start, bucket < now)
        )
    ).one()
    reviews = int(review_row[0] or 0)
    avg_rating = round(float(review_row[1]), 2) if review_row[1] is not None else None

    by_channel_rows = (
        await db.execute(
            select(ReviewRequest.channel, func.count()).where(*req_filters).group_by(ReviewRequest.channel)
        )
    ).all()
    by_trigger_rows = (
        await db.execute(
            select(ReviewRequest.trigger, func.count()).where(*req_filters).group_by(ReviewRequest.trigger)
        )
    ).all()

    funnel = {
        "requests_sent": requests_sent,
        "delivered": delivered,
        "clicked": clicked,
        "failed": failed,
        "reviews": reviews,
        "reviews_via_request": attributed,
        "conversion_rate": _pct(attributed, requests_sent),
        "avg_rating": avg_rating,
        "delivery_tracked": delivered > 0,
        "click_tracked": clicked > 0,
        "attribution_window_days": ATTRIBUTION_WINDOW_DAYS,
        "by_channel": [{"channel": c or "unknown", "requests": int(n or 0)} for c, n in by_channel_rows],
        "by_trigger": [{"trigger": t or "manual", "requests": int(n or 0)} for t, n in by_trigger_rows],
    }

    # ── New contacts by platform (stored rollup) ──────────────────────────
    today = now.date()
    cur_start = today - timedelta(days=days - 1)
    prev_end = cur_start
    prev_start = prev_end - timedelta(days=days)
    m_filters = [ChannelDailyMetric.user_id == user_id]
    if channel_id:
        m_filters.append(ChannelDailyMetric.channel_id == channel_id)
    contact_rows = (
        await db.execute(
            select(Channel.platform, func.sum(ChannelDailyMetric.contacts_new))
            .join(Channel, Channel.id == ChannelDailyMetric.channel_id)
            .where(*m_filters, ChannelDailyMetric.date >= cur_start)
            .group_by(Channel.platform)
        )
    ).all()
    prior_contacts = (
        await db.execute(
            select(func.sum(ChannelDailyMetric.contacts_new)).where(
                *m_filters,
                ChannelDailyMetric.date >= prev_start,
                ChannelDailyMetric.date < prev_end,
            )
        )
    ).scalar() or 0
    new_contacts = sum(int(n or 0) for _p, n in contact_rows)
    contacts = {
        "new_contacts": new_contacts,
        "prior_contacts": int(prior_contacts),
        "delta_pct": (
            round(((new_contacts - prior_contacts) / prior_contacts) * 100.0, 1)
            if prior_contacts
            else None
        ),
        "by_platform": [
            {"platform": p or "unknown", "contacts": int(n or 0)}
            for p, n in sorted(contact_rows, key=lambda r: -(int(r[1] or 0)))
        ],
        "attribution": "unknown",
    }

    # ── Growth actions: deterministic, tied to the numbers above ──────────
    actions: list[dict] = []
    if requests_sent == 0 and new_contacts > 0:
        actions.append({
            "kind": "ask",
            "title": f"Ask your {new_contacts} new contacts for a review",
            "detail": "No review requests recorded this period. Start with WhatsApp or an in-person QR.",
            "expected": "3-10% conversion is a realistic first target",
            "href": "/dashboard/reviews?ask=1",
        })
    if requests_sent > 0 and (funnel["conversion_rate"] or 0) < 5:
        actions.append({
            "kind": "timing",
            "title": "Shift asks to the moment of service",
            "detail": "In-person QR and same-day asks convert better than next-day email.",
            "expected": "Lift request-to-review conversion",
            "href": "/dashboard/reviews?ask=1",
        })
    if requests_sent == 0 and new_contacts == 0:
        actions.append({
            "kind": "connect",
            "title": "Connect a messaging channel",
            "detail": "The ask loop needs a way to reach customers. WhatsApp is the fastest start.",
            "expected": "Unlocks review requests",
            "href": "/dashboard/channels",
        })
    unanswered = (
        await db.execute(
            select(func.count()).where(
                *base,
                ReviewInsight.replied.is_(False),
            )
        )
    ).scalar() or 0
    if unanswered:
        actions.append({
            "kind": "reply",
            "title": f"Reply to {int(unanswered)} unanswered reviews",
            "detail": "Unanswered reviews depress the response rate and lose the customer.",
            "expected": "Improves rating and retention",
            "href": "/dashboard/reviews?status=unanswered",
        })
    if requests_sent > 0 and attributed > 0:
        actions.append({
            "kind": "double_down",
            "title": f"Repeat the request that produced {attributed} reviews",
            "detail": "Look at the by-channel split and do more of the winning channel.",
            "expected": "Compounding review volume",
            "href": "/dashboard/reviews?ask=1",
        })

    return {
        "days": days,
        "funnel": funnel,
        "contacts": contacts,
        "retention": {
            "available": False,
            "reason": "POS/CRM visit history is not connected. Retention cohorts need first-visit and repeat-visit data.",
        },
        "actions": actions[:MAX_ACTIONS],
    }

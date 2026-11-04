"""Soft removal detection for Google reviews.

Google stops returning a review when the reviewer deletes it or Google
removes it. The row (and its replies) stay in the database so history is not
lost and the flag clears automatically if the review reappears. This module is
provider-agnostic: it compares the ids present in a complete fetch with the
stored rows.

Two brakes protect a live listing from a truncated response:
  * a review must be missing from MISSES_BEFORE_REMOVAL consecutive sweeps;
  * one sweep may never remove more than MAX_REMOVAL_RATIO of a channel.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..analytics.models import ReviewInsight
from ..notifications.service import MAX_PER_SYNC, notify
from .models import Channel

logger = logging.getLogger(__name__)

MIN_REVIEWS_FOR_REMOVAL_SWEEP = 5
MISSES_BEFORE_REMOVAL = 2
MAX_REMOVAL_RATIO = 0.34


async def mark_removed_reviews(
    db: AsyncSession, channel: Channel, user_id: str, seen_ids: set[str]
) -> list[str]:
    """Soft-mark reviews that a complete fetch no longer returns."""
    if len(seen_ids) < MIN_REVIEWS_FOR_REMOVAL_SWEEP:
        return []

    candidates = (
        await db.execute(
            select(ReviewInsight).where(
                ReviewInsight.channel_id == channel.id,
                ReviewInsight.removed_at.is_(None),
            )
        )
    ).scalars().all()

    now = datetime.now(timezone.utc)
    removed: list[str] = []
    touched_days: set[date] = set()
    considered = 0
    for insight in candidates:
        if insight.review_id in seen_ids:
            insight.missed_syncs = 0
            insight.last_seen_at = now
            if insight.removed_at is not None:
                insight.removed_at = None
            continue
        if insight.skipped:
            continue
        # Never judge a review we have not successfully sighted at least once.
        if insight.last_seen_at is None:
            continue
        considered += 1
        insight.missed_syncs = (insight.missed_syncs or 0) + 1
        if insight.missed_syncs < MISSES_BEFORE_REMOVAL:
            continue
        insight.removed_at = now
        insight.missed_syncs = 0
        removed.append(insight.review_id)
        touched_days.add((insight.review_updated_at or insight.created_at).date())

    if considered and len(removed) > max(1, int(considered * MAX_REMOVAL_RATIO)):
        logger.error(
            "Removal sweep ABORTED for channel %s: would remove %d of %d unseen "
            "reviews in one sync (limit %d%%). Fetch looks unreliable — leaving "
            "every review in place.",
            channel.id, len(removed), considered, int(MAX_REMOVAL_RATIO * 100),
        )
        for insight in candidates:
            insight.missed_syncs = 0
            if insight.review_id in set(removed):
                insight.removed_at = None
        return []

    if removed:
        await db.commit()
        for review_id in removed[:MAX_PER_SYNC]:
            await notify(
                db, user_id, "review_removed",
                "A review is no longer available on Google",
                "The reviewer deleted it, or Google removed it. Your copy is kept "
                "for reference and the review comes back automatically if it returns.",
                data={"review_id": review_id, "channel_id": channel.id},
                href="/dashboard/reviews",
            )
        from ..analytics.consumer import recompute_daily_rollup

        for day in touched_days:
            try:
                await recompute_daily_rollup(channel.id, user_id, day)
            except Exception as e:  # noqa: BLE001
                logger.warning("rollup recompute after removal failed: %s", e)
    return removed

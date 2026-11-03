"""Daily timeseries: rollups stay authoritative, source rows heal gaps."""
from datetime import datetime, timedelta, timezone

import pytest

from app.modules.analytics.models import LocationDailyMetric, ReviewInsight
from app.modules.analytics.service import get_timeseries
from app.modules.channels.models import ReviewReply


def _review(
    db,
    user_id,
    channel_id,
    idx: int,
    rating: int,
    *,
    sentiment: str,
    replied: bool = False,
    days_ago: int = 0,
) -> str:
    review_id = f"review-{idx}"
    when = datetime.now(timezone.utc) - timedelta(days=days_ago)
    db.add(ReviewInsight(
        id=f"insight-{idx}",
        user_id=user_id,
        channel_id=channel_id,
        review_id=review_id,
        rating=rating,
        review_text="ok",
        reviewer_name=f"Guest {idx}",
        sentiment=sentiment,
        sentiment_score=0.8 if sentiment == "positive" else -0.6,
        topics=[],
        products=[],
        problems=[],
        enrichment_status="done",
        replied=replied,
        review_updated_at=when,
    ))
    return review_id


@pytest.mark.asyncio
async def test_timeseries_falls_back_to_reviews_when_no_daily_row_exists(
    db, user_id, channel_id
):
    replied_review = _review(
        db, user_id, channel_id, 1, 5, sentiment="positive", replied=True
    )
    _review(db, user_id, channel_id, 2, 3, sentiment="negative")
    db.add(ReviewReply(
        id="reply-1",
        channel_id=channel_id,
        review_id=replied_review,
        rating=5,
        reply_text="Thanks!",
        status="posted",
    ))
    await db.commit()

    rows = await get_timeseries(db, user_id, channel_id, days=30)

    assert len(rows) == 1
    row = rows[0]
    assert row.reviews_count == 2
    assert row.avg_rating == 4.0
    assert row.positive_count == 1
    assert row.negative_count == 1
    assert row.replies_count == 1
    assert row.impressions_maps_desktop == 0


@pytest.mark.asyncio
async def test_timeseries_fills_zero_review_performance_row(
    db, user_id, channel_id
):
    today = datetime.now(timezone.utc).date()
    db.add(LocationDailyMetric(
        id="daily-1",
        user_id=user_id,
        channel_id=channel_id,
        date=today,
        reviews_count=0,
        impressions_maps_desktop=120,
        impressions_maps_mobile=30,
    ))
    _review(db, user_id, channel_id, 1, 4, sentiment="positive")
    await db.commit()

    rows = await get_timeseries(db, user_id, channel_id, days=30)

    assert len(rows) == 1
    row = rows[0]
    assert row.reviews_count == 1
    assert row.avg_rating == 4.0
    # The performance half of the row is preserved, not overwritten.
    assert row.impressions_maps_desktop == 120
    assert row.impressions_maps_mobile == 30


@pytest.mark.asyncio
async def test_timeseries_keeps_a_populated_rollup_authoritative(
    db, user_id, channel_id
):
    today = datetime.now(timezone.utc).date()
    db.add(LocationDailyMetric(
        id="daily-2",
        user_id=user_id,
        channel_id=channel_id,
        date=today,
        reviews_count=7,
        avg_rating=4.7,
    ))
    _review(db, user_id, channel_id, 1, 5, sentiment="positive")
    _review(db, user_id, channel_id, 2, 4, sentiment="positive")
    await db.commit()

    rows = await get_timeseries(db, user_id, channel_id, days=30)

    assert len(rows) == 1
    assert rows[0].reviews_count == 7
    assert rows[0].avg_rating == 4.7

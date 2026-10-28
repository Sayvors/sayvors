"""Review-request delivery, click tracking, and per-request attribution."""
from datetime import datetime, timedelta, timezone

import pytest

from app.modules.analytics.models import ReviewRequest
from app.modules.analytics.review_requests import (
    attribute_reviews,
    create_and_deliver,
    track_click,
)


def test_attribute_reviews_one_review_per_click():
    now = datetime.now(timezone.utc)
    clicks = [now - timedelta(days=2), now - timedelta(days=1)]
    reviews = [now, now]
    # Two clicks, two reviews -> two attributed.
    assert attribute_reviews(clicks, reviews, 7) == 2


def test_attribute_reviews_outside_window():
    now = datetime.now(timezone.utc)
    assert attribute_reviews([now - timedelta(days=30)], [now], 7) == 0


def test_attribute_reviews_no_clicks():
    now = datetime.now(timezone.utc)
    assert attribute_reviews([], [now], 7) == 0
    assert attribute_reviews([None], [None], 7) == 0


@pytest.mark.asyncio
async def test_sms_failure_is_visible_when_provider_missing(db, user_id, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "TWILIO_ACCOUNT_SID", "")
    monkeypatch.setattr(settings, "TWILIO_AUTH_TOKEN", "")
    monkeypatch.setattr(settings, "TWILIO_FROM_NUMBER", "")

    row = await create_and_deliver(
        db, user_id, channel_id=None, contact="+966500000000",
        contact_name="Sara", channel="sms", trigger="manual", deliver=True,
    )
    assert row.status == "failed"
    assert row.sent_via == "sms"
    assert "not configured" in (row.error or "").lower()


@pytest.mark.asyncio
async def test_click_marks_row_and_returns_target(db, user_id):
    row = ReviewRequest(
        id="req-click", user_id=user_id, contact="+966500000000",
        channel="whatsapp", trigger="manual", status="sent",
        token="tok-123", review_url="https://search.google.com/local/writereview?placeid=abc",
        sent_at=datetime.now(timezone.utc),
    )
    db.add(row)
    await db.commit()

    target = await track_click(db, "tok-123")
    assert target == "https://search.google.com/local/writereview?placeid=abc"
    await db.refresh(row)
    assert row.clicked_at is not None
    assert row.status == "clicked"

    assert await track_click(db, "unknown-token") is None

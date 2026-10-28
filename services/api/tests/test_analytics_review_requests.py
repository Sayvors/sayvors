"""Review-request delivery, click tracking, and per-request attribution."""
from datetime import datetime, timedelta, timezone

import pytest

from app.modules.analytics.models import ReviewRequest
from app.modules.analytics.review_requests import (
    attribute_reviews,
    create_and_deliver,
    create_queued,
    deliver_request,
    render_template,
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
async def test_whatsapp_failure_is_visible_when_no_number_connected(db, user_id):
    row = await create_and_deliver(
        db, user_id, channel_id=None, contact="+966500000000",
        contact_name="Sara", channel="whatsapp", trigger="manual", deliver=True,
    )
    assert row.status == "failed"
    assert row.sent_via == "whatsapp"
    assert "no connected whatsapp" in (row.error or "").lower()


def test_render_template_placeholders():
    assert render_template("Hi {name}, review: {link}", "Sara", "https://x") == "Hi Sara, review: https://x"
    assert render_template("Hi {name}", None, None) == "Hi there"
    assert render_template(None, "Sara", "x") is None


@pytest.mark.asyncio
async def test_queued_request_uses_template_and_fails_visibly(db, user_id):
    row = await create_queued(
        db, user_id, channel_id=None, contact="+966500000000",
        contact_name="Sara", channel="whatsapp", trigger="campaign",
        subject="Leave a review", body="Hi {name}, please review: {link}",
    )
    assert row.status == "queued"
    await db.commit()

    await deliver_request(db, row)
    assert row.status == "failed"
    assert row.sent_via == "whatsapp"
    assert "no connected whatsapp" in (row.error or "").lower()


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

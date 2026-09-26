"""Regression tests: an already-replied review must still be updatable.

A review can be flagged replied with NO ReviewReply row: the reply was
published outside Sayvors, so the "replied" Kafka event set the flag
without ever creating a row. The insights payload then carries no
reply_id / reply_text, which left the review detail page promising "you can
still draft an updated response below" while rendering no way to do it.

The recovery path is generate(custom_text) — it must create a fresh
approvable draft rather than refusing the way it does for a row that is
already live on Google.
"""
from datetime import datetime, timezone

import pytest

from app.modules.analytics.models import ReviewInsight


@pytest.mark.asyncio
async def test_generate_creates_draft_for_replied_review_with_no_row(
    db, client, user_id, channel_id
):
    db.add(ReviewInsight(
        id="ins-replied-no-row", user_id=user_id, channel_id=channel_id,
        review_id="ggreview-orphan", rating=4,
        review_text="In the new version there is a lot of new things to see.",
        reviewer_name="Syed Syab Ahmad Shah", sentiment="neutral",
        sentiment_score=0.5, topics=[], products=[], problems=[],
        enrichment_status="done", replied=True, skipped=False,
        replied_at=datetime.now(timezone.utc),
    ))
    await db.commit()

    # The insight really does carry no response row.
    listing = client.get("/api/v1/analytics/reviews/insights")
    assert listing.status_code == 200, listing.text
    item = next(
        i for i in listing.json()["items"] if i["review_id"] == "ggreview-orphan"
    )
    assert item["replied"] is True
    assert item["reply_id"] is None
    assert item["reply_text"] is None

    # The update path: draft with the merchant's own words (skips the LLM).
    made = client.post(
        f"/api/v1/channels/{channel_id}/reviews/generate",
        json={
            "review_id": "ggreview-orphan",
            "rating": 4,
            "review_text": "In the new version there is a lot of new things to see.",
            "reviewer_name": "Syed Syab Ahmad Shah",
            "custom_text": "Thanks for the kind words, and for staying with us!",
        },
    )
    assert made.status_code == 201, made.text
    row = made.json()
    assert row["status"] == "pending_approval"
    assert row["reply_text"] == "Thanks for the kind words, and for staying with us!"

    # Now it is a real, editable response on the review detail page.
    listing = client.get("/api/v1/analytics/reviews/insights")
    item = next(
        i for i in listing.json()["items"] if i["review_id"] == "ggreview-orphan"
    )
    assert item["reply_id"] == row["id"]
    assert item["reply_status"] == "pending_approval"


@pytest.mark.asyncio
async def test_generate_refuses_second_draft_when_reply_is_live(
    db, client, user_id, channel_id
):
    """A live Google reply must not be silently duplicated.

    generate() allows a follow-up draft only when the reviewer edited the
    review after we answered. Otherwise it 409s, so a merchant cannot stack
    competing replies on one review.
    """
    from app.modules.channels.models import ReviewReply

    db.add(ReviewInsight(
        id="ins-replied-live", user_id=user_id, channel_id=channel_id,
        review_id="ggreview-live", rating=5, review_text="Great",
        reviewer_name="Sara", sentiment="positive", sentiment_score=0.9,
        topics=[], products=[], problems=[], enrichment_status="done",
        replied=True, skipped=False, edited=False,
        replied_at=datetime.now(timezone.utc),
    ))
    db.add(ReviewReply(
        id="rr-live", channel_id=channel_id, review_id="ggreview-live",
        rating=5, reply_text="Thanks so much!", status="posted",
    ))
    await db.commit()

    made = client.post(
        f"/api/v1/channels/{channel_id}/reviews/generate",
        json={"review_id": "ggreview-live", "rating": 5, "custom_text": "Again!"},
    )
    assert made.status_code == 409, made.text

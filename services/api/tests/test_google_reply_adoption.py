"""Native Google replies already on the listing are adopted, not overwritten."""
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.modules.channels.google_reviews import GoogleReview
from app.modules.channels.models import Channel, ReviewReply
from app.modules.channels.reviews_worker import _adopt_existing_reply


def _review(**overrides) -> GoogleReview:
    base = dict(
        review_id="accounts/a/locations/l/reviews/r1",
        rating=4,
        text="Great service",
        reviewer_name="A customer",
        has_reply=True,
        reply_text="Thanks for visiting!",
        reply_updated_at=datetime(2026, 9, 30, 10, 28, 52, tzinfo=timezone.utc),
    )
    base.update(overrides)
    return GoogleReview(**base)


async def _rows(db, channel_id: str, review_id: str):
    return (
        await db.execute(
            select(ReviewReply).where(
                ReviewReply.channel_id == channel_id,
                ReviewReply.review_id == review_id,
            )
        )
    ).scalars().all()


@pytest.mark.asyncio
async def test_existing_google_reply_is_imported_as_posted(db, channel_id):
    channel = await db.get(Channel, channel_id)

    assert await _adopt_existing_reply(db, channel, _review()) is True

    rows = await _rows(db, channel_id, "accounts/a/locations/l/reviews/r1")
    assert len(rows) == 1
    assert rows[0].status == "posted"
    assert rows[0].reply_text == "Thanks for visiting!"
    assert rows[0].reply_external_id == "google:2026-09-30T10:28:52+00:00"
    assert rows[0].replied_at is not None


@pytest.mark.asyncio
async def test_adoption_is_idempotent_and_does_not_duplicate(db, channel_id):
    channel = await db.get(Channel, channel_id)
    assert await _adopt_existing_reply(db, channel, _review()) is True
    assert await _adopt_existing_reply(db, channel, _review()) is False

    assert len(await _rows(db, channel_id, "accounts/a/locations/l/reviews/r1")) == 1


@pytest.mark.asyncio
async def test_pending_draft_is_superseded_by_the_live_google_reply(db, channel_id):
    channel = await db.get(Channel, channel_id)
    db.add(ReviewReply(
        id="draft-1",
        channel_id=channel_id,
        review_id="accounts/a/locations/l/reviews/r1",
        rating=4,
        reply_text="AI draft that was never published",
        status="pending_approval",
    ))
    await db.commit()

    assert await _adopt_existing_reply(db, channel, _review()) is True

    rows = await _rows(db, channel_id, "accounts/a/locations/l/reviews/r1")
    assert len(rows) == 1
    assert rows[0].status == "posted"
    assert rows[0].reply_text == "Thanks for visiting!"
    assert rows[0].error is None


@pytest.mark.asyncio
async def test_google_reply_edited_in_gbp_corrects_the_row(db, channel_id):
    channel = await db.get(Channel, channel_id)
    await _adopt_existing_reply(db, channel, _review())

    edited = _review(
        reply_text="Edited in the Business Profile",
        reply_updated_at=datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc),
    )
    assert await _adopt_existing_reply(db, channel, edited) is True

    rows = await _rows(db, channel_id, "accounts/a/locations/l/reviews/r1")
    assert len(rows) == 1
    assert rows[0].reply_text == "Edited in the Business Profile"
    assert rows[0].reply_external_id == "google:2026-10-01T09:00:00+00:00"


@pytest.mark.asyncio
async def test_no_live_reply_writes_nothing(db, channel_id):
    channel = await db.get(Channel, channel_id)
    assert await _adopt_existing_reply(
        db, channel, _review(has_reply=False, reply_text=None)
    ) is False
    assert await _rows(db, channel_id, "accounts/a/locations/l/reviews/r1") == []

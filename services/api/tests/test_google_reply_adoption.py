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
async def test_same_provider_reply_does_not_rebaseline_an_edited_review(db, channel_id):
    """Google normalising our reply's text is not a new reply.

    The row's rating/review_text describe what that reply answered. Stamping
    the review's new content onto it marked an edited review as answered by
    the response written for its old content, so the follow-up draft that
    should answer the edit could never be detected — saeed's 1-star complaint
    edited into a 5-star thank-you kept the old apology as its reply.
    """
    channel = await db.get(Channel, channel_id)
    await _adopt_existing_reply(db, channel, _review(rating=1, text="Old complaint"))

    edited = _review(
        rating=5,
        text="Thank you for getting in touch",
        # Same provider update time; Google trimmed the trailing space.
        reply_text="Thanks for visiting!  ",
    )
    assert await _adopt_existing_reply(db, channel, edited) is False

    rows = await _rows(db, channel_id, "accounts/a/locations/l/reviews/r1")
    assert len(rows) == 1
    row = rows[0]
    assert row.status == "posted"
    assert row.rating == 1
    assert row.review_text == "Old complaint"
    assert row.reply_text == "Thanks for visiting!"


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
async def test_reply_envelope_without_comment_preserves_published_text(db, channel_id):
    """A transient comment-less Google payload must not erase our known reply.

    Onboarding can successfully write a reply while immediate readback is
    still absent, leaving no provider timestamp. A later poll may see the
    reply envelope before Google returns its comment. Treating that envelope
    as new blanked the published text and produced "Replied on Google" with
    nothing for the merchant to read or edit.
    """
    channel = await db.get(Channel, channel_id)
    db.add(ReviewReply(
        id="posted-without-readback",
        channel_id=channel_id,
        review_id="accounts/a/locations/l/reviews/r1",
        rating=4,
        reply_text="Thanks for visiting!",
        status="posted",
        reply_external_id=None,
    ))
    await db.commit()

    assert await _adopt_existing_reply(
        db,
        channel,
        _review(
            reply_text=None,
            reply_updated_at=datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc),
            reply_state="pending",
        ),
    ) is True

    rows = await _rows(db, channel_id, "accounts/a/locations/l/reviews/r1")
    assert len(rows) == 1
    row = rows[0]
    assert row.status == "posted"
    assert row.reply_text == "Thanks for visiting!"
    assert row.reply_external_id == "google:2026-10-02T09:00:00+00:00"
    assert row.google_reply_state == "pending"


@pytest.mark.asyncio
async def test_same_provider_reply_restores_text_after_comment_lag(db, channel_id):
    """Heal rows the old comment-less adoption path already blanked."""
    channel = await db.get(Channel, channel_id)
    reviewed_at = datetime(2026, 9, 30, 10, 28, 52, tzinfo=timezone.utc)
    db.add(ReviewReply(
        id="blanked-posted-reply",
        channel_id=channel_id,
        review_id="accounts/a/locations/l/reviews/r1",
        rating=4,
        reply_text="",
        status="posted",
        reply_external_id=f"google:{reviewed_at.isoformat()}",
    ))
    await db.commit()

    assert await _adopt_existing_reply(db, channel, _review()) is True

    rows = await _rows(db, channel_id, "accounts/a/locations/l/reviews/r1")
    assert len(rows) == 1
    assert rows[0].reply_text == "Thanks for visiting!"


@pytest.mark.asyncio
async def test_no_live_reply_writes_nothing(db, channel_id):
    channel = await db.get(Channel, channel_id)
    assert await _adopt_existing_reply(
        db, channel, _review(has_reply=False, reply_text=None)
    ) is False
    assert await _rows(db, channel_id, "accounts/a/locations/l/reviews/r1") == []


@pytest.mark.asyncio
async def test_unchanged_google_reply_keeps_a_followup_draft(db, channel_id):
    """A follow-up draft for an edited review must survive polling.

    Google keeps showing the (older) reply the follow-up is meant to replace.
    Re-adopting it would silently discard the only draft the merchant can act
    on, so the row is left alone while the provider update time is unchanged.
    """
    channel = await db.get(Channel, channel_id)
    await _adopt_existing_reply(db, channel, _review())

    row = (await _rows(db, channel_id, "accounts/a/locations/l/reviews/r1"))[0]
    row.status = "pending_approval"
    row.reply_text = "follow-up for the edited review"
    row.review_text = "Updated review text"
    row.rating = 5
    await db.commit()

    assert await _adopt_existing_reply(db, channel, _review()) is False

    rows = await _rows(db, channel_id, "accounts/a/locations/l/reviews/r1")
    assert len(rows) == 1
    assert rows[0].status == "pending_approval"
    assert rows[0].reply_text == "follow-up for the edited review"
    assert rows[0].review_text == "Updated review text"


@pytest.mark.asyncio
async def test_reply_edited_in_gbp_replaces_a_pending_draft(db, channel_id):
    """A reply actually changed in the Business Profile still wins: only an
    unchanged provider reply is skipped."""
    channel = await db.get(Channel, channel_id)
    await _adopt_existing_reply(db, channel, _review())

    row = (await _rows(db, channel_id, "accounts/a/locations/l/reviews/r1"))[0]
    row.status = "pending_approval"
    row.reply_text = "follow-up for the edited review"
    await db.commit()

    edited = _review(
        reply_text="Edited in the Business Profile",
        reply_updated_at=datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc),
    )
    assert await _adopt_existing_reply(db, channel, edited) is True

    rows = await _rows(db, channel_id, "accounts/a/locations/l/reviews/r1")
    assert len(rows) == 1
    assert rows[0].status == "posted"
    assert rows[0].reply_text == "Edited in the Business Profile"

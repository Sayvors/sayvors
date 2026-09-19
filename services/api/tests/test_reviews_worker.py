"""Regression tests: the polling worker must RESUME a failed ReviewReply
row instead of inserting a fresh draft for the same review.

Before the fix, `_already_replied` ignored `failed` rows and the worker
created a new `pending_approval` row on the next poll — the same review
then appeared in both the "needs approval" and "failed to publish"
queues on the dashboard.
"""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.modules.channels import reviews_worker
from app.modules.channels.models import AutoReplyConfig, Channel, ReviewReply
from app.modules.channels.service import encrypt_token


def _review(review_id="ggreview-1", rating=2):
    return SimpleNamespace(
        review_id=review_id,
        rating=rating,
        text="Terrible service, never again.",
        reviewer_name="Angry Customer",
        updated_at=datetime.now(timezone.utc),
    )


class FakeGoogleClient:
    def __init__(self, access_token, refresh_token):
        self.posted = []

    def set_known_expiry(self, expires_at):
        pass

    def set_token_persister(self, persister):
        pass

    async def list_locations(self, account_id):
        return []

    async def list_reviews(self, account_id, location_id, updated_after=None):
        return FakeGoogleClient.reviews

    async def reply_to_review(self, review_id, text):
        FakeGoogleClient.posted.append((review_id, text))

    async def confirm_reply_live(self, review_id, attempts=2):
        return True

    async def close(self):
        pass


def _install_fakes(monkeypatch, reviews, generate=None):
    FakeGoogleClient.posted = []
    FakeGoogleClient.reviews = reviews
    monkeypatch.setattr(reviews_worker.settings, "GOOGLE_REVIEWS_MOCK", False)
    monkeypatch.setattr(reviews_worker, "GoogleReviewsClient", FakeGoogleClient)

    async def _generate(config, channel, rating, text, reviewer_name, db,
                       review_id=None, attempt=1, previous_draft=None):
        return f"fresh AI draft (try {attempt})"

    monkeypatch.setattr(reviews_worker, "generate_auto_reply", generate or _generate)


async def _active_channel(db, channel_id):
    channel = await db.get(Channel, channel_id)
    channel.access_token = encrypt_token("fake-access-token")
    await db.commit()
    return channel


async def _reply_rows(db, channel_id, review_id):
    result = await db.execute(
        select(ReviewReply)
        .where(
            ReviewReply.channel_id == channel_id,
            ReviewReply.review_id == review_id,
        )
        .order_by(ReviewReply.created_at.asc())
    )
    return result.scalars().all()


@pytest.mark.asyncio
async def test_low_rating_failure_is_resumed_not_duplicated(
    db, channel_id, config_id, monkeypatch
):
    await _active_channel(db, channel_id)
    db.add(
        ReviewReply(
            channel_id=channel_id,
            review_id="ggreview-1",
            rating=2,
            review_text="Terrible service, never again.",
            reviewer_name="Angry Customer",
            reply_text="old draft",
            status="failed",
            error="Google said 503",
        )
    )
    await db.commit()

    _install_fakes(monkeypatch, [_review(rating=2)])
    stats = await reviews_worker.process_channel(
        db, await db.get(Channel, channel_id),
        await db.get(AutoReplyConfig, config_id),
    )

    assert stats["queued"] == 1
    rows = await _reply_rows(db, channel_id, "ggreview-1")
    assert len(rows) == 1
    assert rows[0].status == "pending_approval"
    assert rows[0].reply_text == "fresh AI draft (try 2)"
    assert rows[0].generation_attempt == 2
    assert rows[0].error is None


@pytest.mark.asyncio
async def test_autopost_failure_is_resumed_not_duplicated(
    db, channel_id, config_id, monkeypatch
):
    await _active_channel(db, channel_id)
    db.add(
        ReviewReply(
            channel_id=channel_id,
            review_id="ggreview-1",
            rating=5,
            review_text="Great!",
            reviewer_name="Happy",
            reply_text="old draft",
            status="failed",
            error="Google said 503",
        )
    )
    await db.commit()

    _install_fakes(monkeypatch, [_review(rating=5)])
    await reviews_worker.process_channel(
        db, await db.get(Channel, channel_id),
        await db.get(AutoReplyConfig, config_id),
    )

    rows = await _reply_rows(db, channel_id, "ggreview-1")
    assert len(rows) == 1
    assert rows[0].status == "posted"
    assert rows[0].generation_attempt == 2
    assert rows[0].error is None


@pytest.mark.asyncio
async def test_regeneration_failure_keeps_single_failed_row(
    db, channel_id, config_id, monkeypatch
):
    await _active_channel(db, channel_id)
    db.add(
        ReviewReply(
            channel_id=channel_id,
            review_id="ggreview-1",
            rating=2,
            review_text="Terrible",
            reviewer_name="A",
            reply_text="old draft",
            status="failed",
            error="old error",
        )
    )
    await db.commit()

    async def _boom(config, channel, rating, text, reviewer_name, db,
                    review_id=None, attempt=1, previous_draft=None):
        raise RuntimeError("LLM down")

    _install_fakes(monkeypatch, [_review(rating=2)], generate=_boom)
    stats = await reviews_worker.process_channel(
        db, await db.get(Channel, channel_id),
        await db.get(AutoReplyConfig, config_id),
    )

    assert stats["errors"] == 1
    rows = await _reply_rows(db, channel_id, "ggreview-1")
    assert len(rows) == 1
    assert rows[0].status == "failed"
    assert "LLM down" in rows[0].error
    assert rows[0].reply_text == "old draft"


@pytest.mark.asyncio
async def test_legacy_duplicate_failed_rows_collapse(
    db, channel_id, config_id, monkeypatch
):
    await _active_channel(db, channel_id)
    db.add(
        ReviewReply(
            channel_id=channel_id, review_id="ggreview-1", rating=2,
            reply_text="oldest", status="failed", error="e1",
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
    )
    db.add(
        ReviewReply(
            channel_id=channel_id, review_id="ggreview-1", rating=2,
            reply_text="newest", status="failed", error="e2",
            created_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )
    )
    await db.commit()

    _install_fakes(monkeypatch, [_review(rating=2)])
    await reviews_worker.process_channel(
        db, await db.get(Channel, channel_id),
        await db.get(AutoReplyConfig, config_id),
    )

    rows = await _reply_rows(db, channel_id, "ggreview-1")
    statuses = sorted(r.status for r in rows)
    assert statuses == ["pending_approval", "rejected"]
    resumed = next(r for r in rows if r.status == "pending_approval")
    assert resumed.reply_text == "fresh AI draft (try 2)"
    assert resumed.generation_attempt == 2


@pytest.mark.asyncio
async def test_posted_review_still_skipped(db, channel_id, config_id, monkeypatch):
    await _active_channel(db, channel_id)
    db.add(
        ReviewReply(
            channel_id=channel_id, review_id="ggreview-1", rating=5,
            reply_text="live", status="posted",
        )
    )
    await db.commit()

    _install_fakes(monkeypatch, [_review(rating=5)])
    stats = await reviews_worker.process_channel(
        db, await db.get(Channel, channel_id),
        await db.get(AutoReplyConfig, config_id),
    )

    assert stats["skipped"] == 1
    rows = await _reply_rows(db, channel_id, "ggreview-1")
    assert len(rows) == 1
    assert rows[0].status == "posted"

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
        # Returns (text, needs_review) — generate_auto_reply's contract.
        return f"fresh AI draft (try {attempt})", False

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


@pytest.mark.asyncio
async def test_edited_review_regenerates_pending_draft(db, channel_id, config_id, monkeypatch):
    """Reviewer changed the review while a draft was queued: the draft is
    regenerated from the new content in place — same row, no auto-post."""
    await _active_channel(db, channel_id)
    db.add(
        ReviewReply(
            channel_id=channel_id, review_id="ggreview-1", rating=2,
            review_text="Old complaint text", reviewer_name="Angry Customer",
            reply_text="old draft", status="pending_approval",
        )
    )
    await db.commit()

    _install_fakes(monkeypatch, [_review(rating=2)])
    stats = await reviews_worker.process_channel(
        db, await db.get(Channel, channel_id),
        await db.get(AutoReplyConfig, config_id),
    )

    assert stats["skipped"] == 1
    rows = await _reply_rows(db, channel_id, "ggreview-1")
    assert len(rows) == 1
    row = rows[0]
    assert row.status == "pending_approval"
    assert row.review_text == "Terrible service, never again."
    assert row.reply_text == "fresh AI draft (try 2)"
    assert row.generation_attempt == 2
    assert FakeGoogleClient.posted == []


@pytest.mark.asyncio
async def test_edited_review_after_posted_reply_queues_followup(db, channel_id, config_id, monkeypatch):
    """Reviewer changed the review after our reply went live: a follow-up
    draft is queued for approval — the posted reply is never re-posted."""
    await _active_channel(db, channel_id)
    db.add(
        ReviewReply(
            channel_id=channel_id, review_id="ggreview-1", rating=2,
            review_text="Old complaint text", reviewer_name="Angry Customer",
            reply_text="live reply", status="posted",
        )
    )
    await db.commit()

    _install_fakes(monkeypatch, [_review(rating=1)])
    stats = await reviews_worker.process_channel(
        db, await db.get(Channel, channel_id),
        await db.get(AutoReplyConfig, config_id),
    )

    assert stats["skipped"] == 1
    rows = await _reply_rows(db, channel_id, "ggreview-1")
    assert len(rows) == 2
    posted = [r for r in rows if r.status == "posted"]
    pending = [r for r in rows if r.status == "pending_approval"]
    assert len(posted) == 1 and posted[0].reply_text == "live reply"
    assert len(pending) == 1
    assert pending[0].review_text == "Terrible service, never again."
    assert pending[0].reply_text == "fresh AI draft (try 1)"
    # Follow-ups wait for approval — never posted automatically.
    assert FakeGoogleClient.posted == []


@pytest.mark.asyncio
async def test_edited_review_followup_autoposts_when_opted_in(db, channel_id, config_id, monkeypatch):
    """edited_review_autopost on: the follow-up for an edited review
    auto-posts live — through the same gates as a fresh reply."""
    await _active_channel(db, channel_id)
    db.add(
        ReviewReply(
            channel_id=channel_id, review_id="ggreview-1", rating=2,
            review_text="Old complaint text", reviewer_name="Angry Customer",
            reply_text="live reply", status="posted",
        )
    )
    config = await db.get(AutoReplyConfig, config_id)
    config.edited_review_autopost = True
    await db.commit()

    _install_fakes(monkeypatch, [_review(rating=5)])
    stats = await reviews_worker.process_channel(
        db, await db.get(Channel, channel_id),
        await db.get(AutoReplyConfig, config_id),
    )

    assert stats["skipped"] == 1
    # The follow-up went live: rating 5 clears the min_rating_auto gate.
    assert FakeGoogleClient.posted == [("ggreview-1", "fresh AI draft (try 1)")]
    rows = await _reply_rows(db, channel_id, "ggreview-1")
    assert len(rows) == 2
    assert all(r.status == "posted" for r in rows)
    followup = next(r for r in rows if r.reply_text != "live reply")
    assert followup.rating == 5


@pytest.mark.asyncio
async def test_edited_review_followup_autopost_blocked_below_threshold(db, channel_id, config_id, monkeypatch):
    """edited_review_autopost on, but the edited rating sits below
    min_rating_auto: the follow-up queues for approval like the default."""
    await _active_channel(db, channel_id)
    db.add(
        ReviewReply(
            channel_id=channel_id, review_id="ggreview-1", rating=2,
            review_text="Old complaint text", reviewer_name="Angry Customer",
            reply_text="live reply", status="posted",
        )
    )
    config = await db.get(AutoReplyConfig, config_id)
    config.edited_review_autopost = True
    await db.commit()

    _install_fakes(monkeypatch, [_review(rating=1)])
    await reviews_worker.process_channel(
        db, await db.get(Channel, channel_id),
        await db.get(AutoReplyConfig, config_id),
    )

    assert FakeGoogleClient.posted == []
    rows = await _reply_rows(db, channel_id, "ggreview-1")
    pending = [r for r in rows if r.status == "pending_approval"]
    assert len(pending) == 1 and pending[0].rating == 1


@pytest.mark.asyncio
async def test_edited_review_followup_autopost_blocked_in_approval_mode(db, channel_id, config_id, monkeypatch):
    """approval_mode "approval" overrides the autopost opt-in: every reply
    — edit follow-ups included — waits for the human."""
    await _active_channel(db, channel_id)
    db.add(
        ReviewReply(
            channel_id=channel_id, review_id="ggreview-1", rating=2,
            review_text="Old complaint text", reviewer_name="Angry Customer",
            reply_text="live reply", status="posted",
        )
    )
    config = await db.get(AutoReplyConfig, config_id)
    config.edited_review_autopost = True
    config.approval_mode = "approval"
    await db.commit()

    _install_fakes(monkeypatch, [_review(rating=5)])
    await reviews_worker.process_channel(
        db, await db.get(Channel, channel_id),
        await db.get(AutoReplyConfig, config_id),
    )

    assert FakeGoogleClient.posted == []
    rows = await _reply_rows(db, channel_id, "ggreview-1")
    assert any(r.status == "pending_approval" for r in rows)


@pytest.mark.asyncio
async def test_edited_review_followup_autopost_failure_saves_failed_row(db, channel_id, config_id, monkeypatch):
    """When the live post fails, the follow-up lands in the failed queue
    (resumable) instead of vanishing — the merchant is notified."""
    from app.modules.channels.google_reviews import GoogleReviewsError

    await _active_channel(db, channel_id)
    db.add(
        ReviewReply(
            channel_id=channel_id, review_id="ggreview-1", rating=2,
            review_text="Old complaint text", reviewer_name="Angry Customer",
            reply_text="live reply", status="posted",
        )
    )
    config = await db.get(AutoReplyConfig, config_id)
    config.edited_review_autopost = True
    await db.commit()

    _install_fakes(monkeypatch, [_review(rating=5)])

    async def _boom(self, review_id, text):
        raise GoogleReviewsError("Google said 503")

    monkeypatch.setattr(FakeGoogleClient, "reply_to_review", _boom)
    await reviews_worker.process_channel(
        db, await db.get(Channel, channel_id),
        await db.get(AutoReplyConfig, config_id),
    )

    rows = await _reply_rows(db, channel_id, "ggreview-1")
    failed = [r for r in rows if r.status == "failed"]
    assert len(failed) == 1
    assert failed[0].reply_text == "fresh AI draft (try 1)"
    assert "503" in (failed[0].error or "")


@pytest.mark.asyncio
async def test_dismissed_review_not_redrafted(db, channel_id, config_id, monkeypatch):
    """A rejected draft stays rejected: the poll must not draft again for
    a dismissed review (the merchant answered elsewhere or wants silence)."""
    from app.modules.analytics.models import ReviewInsight

    await _active_channel(db, channel_id)
    db.add(ReviewInsight(
        channel_id=channel_id, review_id="ggreview-1", user_id="u-dismiss-1",
        rating=2, review_text="Terrible service, never again.",
        reviewer_name="Angry Customer", draft_dismissed=True,
    ))
    db.add(
        ReviewReply(
            channel_id=channel_id, review_id="ggreview-1", rating=2,
            review_text="Terrible service, never again.",
            reviewer_name="Angry Customer", reply_text="old draft",
            status="rejected",
        )
    )
    await db.commit()

    calls = []

    async def _counting_generate(config, channel, rating, text, reviewer, db_,
                                 review_id=None, attempt=1, previous_draft=None):
        calls.append(review_id)
        return "should never be called"

    _install_fakes(monkeypatch, [_review(rating=2)], generate=_counting_generate)
    stats = await reviews_worker.process_channel(
        db, await db.get(Channel, channel_id),
        await db.get(AutoReplyConfig, config_id),
    )

    assert calls == []
    assert stats["skipped"] == 1
    rows = await _reply_rows(db, channel_id, "ggreview-1")
    assert len(rows) == 1
    assert rows[0].status == "rejected"


@pytest.mark.asyncio
async def test_pipeline_model_resolution_supplies_required_rating(db, monkeypatch):
    """Model resolution must not be silently skipped by an invalid request.

    ReviewEngineRequest requires a rating even though model resolution only
    reads model/channel_id. The worker used to build it without rating, catch
    the validation error, and pass None into the pipeline -- producing the
    opaque "ValueError: no model" on every review.
    """
    from app.modules.review_engine import graph as review_graph
    from app.modules.review_engine import service as review_service

    channel = Channel(
        id="11111111-1111-1111-1111-111111111111",
        user_id="test-user-0000-0000-0000-000000000001",
        platform="google_reviews",
        platform_user_id="demo-acc-123",
        display_name="Test Burgers",
        status="active",
        access_token=encrypt_token("fake-access-token"),
        metadata_json='{"location_id": "demo-loc-456", "account_id": "demo-acc-123"}',
    )
    config = AutoReplyConfig(
        id="22222222-2222-2222-2222-222222222222",
        channel_id=channel.id,
        enabled=True,
        tone="friendly",
        min_rating_auto=4,
        model=None,
    )
    db.add_all([channel, config])
    await db.commit()

    captured = {}

    async def _resolve(req, tenant_id, session):
        captured["resolved"] = True
        captured["resolver_rating"] = req.rating
        return "openai:gpt-4o-mini", "channel"

    async def _pipeline(session, **state):
        captured.update(state)
        return {}

    monkeypatch.setattr(review_service, "_resolve_engine_model", _resolve)
    monkeypatch.setattr(review_graph, "run_review_pipeline", _pipeline)
    _install_fakes(monkeypatch, [_review(rating=2)])

    await reviews_worker.process_channel(db, channel, config)

    assert captured["resolved"] is True
    assert captured["resolver_rating"] == 2
    assert captured["model"] == "openai:gpt-4o-mini"


# ── poll pass aggregation ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_poll_marks_seen_reviews_for_removal_evidence(
    db, user_id, channel_id
):
    """The daily sweep trusts only sightings written by a real provider fetch."""
    from app.modules.analytics.models import ReviewInsight

    row = ReviewInsight(
        id="seen-review-1", user_id=user_id, channel_id=channel_id,
        review_id="ggreview-seen", rating=5, review_text="Hi",
        reviewer_name="Tester", sentiment="neutral", sentiment_score=0.5,
        topics=[], products=[], problems=[], enrichment_status="done",
    )
    db.add(row)
    await db.commit()
    channel = await db.get(Channel, channel_id)

    await reviews_worker._mark_reviews_seen(db, channel, [_review("ggreview-seen")])
    await db.refresh(row)
    assert row.last_seen_at is not None
    assert row.removed_at is None


@pytest.mark.asyncio
async def test_poll_once_sums_every_channel_field(db, channel_id, config_id, monkeypatch):
    """The pass total must include the channel count, not just review counts."""
    import asyncio

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    factory = async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("app.database.async_session", factory)

    async def _fake(ch_id, cfg_id, semaphore):
        return {"channels": 1, "reviews": 3, "replied": 2, "queued": 1, "skipped": 0, "adopted": 0, "errors": 0}

    monkeypatch.setattr(reviews_worker, "_poll_one_channel", _fake)

    totals = await reviews_worker.poll_once()

    assert totals == {"channels": 1, "reviews": 3, "replied": 2, "queued": 1, "skipped": 0, "adopted": 0, "errors": 0}


@pytest.mark.asyncio
async def test_poll_one_channel_reports_the_channel_it_polled(
    db, channel_id, config_id, monkeypatch
):
    """`channels` must be a key of the per-channel stats dict.

    Regression: `poll_once` sums `result["channels"]` but the dict created in
    `_poll_one_channel` omitted that key. Every due channel therefore died
    with KeyError('channels') before `process_channel` ran — Google reviews
    were never polled at all, while each pass logged a generic failure.
    """
    import asyncio

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    factory = async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("app.database.async_session", factory)

    async def _claim(session, config_id_arg, last_polled_at):
        return True

    async def _release(session, config_id_arg):
        return None

    async def _health(session, channel, ok, error=None):
        return None

    async def _process(session, channel, config):
        return {"reviews": 2, "replied": 1, "queued": 1, "skipped": 0, "errors": 0}

    monkeypatch.setattr(reviews_worker, "_claim_channel", _claim)
    monkeypatch.setattr(reviews_worker, "_release_channel", _release)
    monkeypatch.setattr(reviews_worker, "_update_channel_health", _health)
    monkeypatch.setattr(reviews_worker, "_is_in_health_backoff", lambda channel, now: False)
    monkeypatch.setattr(reviews_worker, "process_channel", _process)

    stats = await reviews_worker._poll_one_channel(
        channel_id, config_id, asyncio.Semaphore(1)
    )

    assert stats["channels"] == 1
    assert stats["reviews"] == 2
    assert stats["replied"] == 1
    # Everything poll_once aggregates must be present, including on the paths
    # that return early (not claimed / in backoff).
    for key in ("channels", "reviews", "replied", "queued", "skipped", "errors"):
        assert key in stats, key


@pytest.mark.asyncio
async def test_google_review_name_and_reply_are_mirrored_into_the_inbox(db, channel_id):
    from app.modules.channels.models import ChannelMessage

    review = SimpleNamespace(
        review_id="accounts/a/locations/l/reviews/chat",
        rating=5,
        text="What service do you offer?",
        reviewer_name="Abdulrahman Manea",
        reviewer_photo_url="https://lh3.googleusercontent.com/avatar",
    )
    await reviews_worker._store_inbound_review(db, channel_id, review)

    inbound = (
        await db.execute(
            select(ChannelMessage).where(
                ChannelMessage.channel_id == channel_id,
                ChannelMessage.platform_message_id == review.review_id,
            )
        )
    ).scalar_one()
    assert inbound.contact_name == "Abdulrahman Manea"
    assert inbound.contact_phone_hash is not None

    channel = await db.get(Channel, channel_id)
    reply = ReviewReply(
        id="rr-chat-mirror",
        channel_id=channel_id,
        review_id=review.review_id,
        rating=5,
        reviewer_name=review.reviewer_name,
        reply_text="Thanks for asking! We offer AI software solutions.",
        status="posted",
    )
    db.add(reply)
    await db.commit()
    await reviews_worker._store_reply_message(
        db, channel, review.review_id, review.reviewer_name, reply,
        status="sent", handled_by="ai",
    )
    await db.commit()

    outbound = (
        await db.execute(
            select(ChannelMessage).where(
                ChannelMessage.channel_id == channel_id,
                ChannelMessage.platform_message_id == "google-reply:rr-chat-mirror",
            )
        )
    ).scalar_one()
    assert outbound.direction == "outbound"
    assert outbound.content_type == "review_reply"
    assert outbound.contact_phone_hash == inbound.contact_phone_hash
    assert outbound.contact_name == "Abdulrahman Manea"


@pytest.mark.asyncio
async def test_removed_location_is_disconnected_not_expired(db, channel_id, monkeypatch):
    """A 404 means the listing is gone, not that the grant died.

    Regression: 404 was in the permanent set, so a deleted/merged location
    marked the whole channel "expired". The token still worked for every
    sibling location, yet the tenant was told to reconnect forever.
    """
    from app.modules.channels.google_reviews import GoogleReviewsError

    notified = []

    async def _notify(db_, user_id, kind, title, body, **kwargs):
        notified.append((kind, title))

    monkeypatch.setattr(reviews_worker, "notify", _notify)

    channel = await db.get(Channel, channel_id)
    channel.status = "active"
    await db.commit()

    await reviews_worker._mark_location_removed(db, channel, "list_reviews failed: 404")
    await db.commit()
    await db.refresh(channel)

    assert channel.status == "disconnected"
    assert notified and notified[0][0] == "channel_removed"

    # Expiry is reserved for a dead grant.
    channel.status = "active"
    await db.commit()
    await reviews_worker._mark_channel_expired(db, channel, "401")
    await db.commit()
    await db.refresh(channel)
    assert channel.status == "expired"


def test_permission_status_classification():
    """Only 401 is immediately terminal; 404 is not a reconnect at all."""
    assert 401 in reviews_worker.TOKEN_DEAD_STATUSES
    assert 404 in reviews_worker.LOCATION_GONE_STATUSES
    assert 403 in reviews_worker.PERMISSION_DENIED_STATUSES
    assert 403 not in reviews_worker.TOKEN_DEAD_STATUSES
    assert reviews_worker.PERMISSION_FAILURES_BEFORE_EXPIRED >= 2


def test_fetch_cursor_applies_propagation_overlap():
    """The fetch window must start before the stored cursor.

    Google's list API lags Maps by minutes; fetching strictly after
    last_polled_at permanently misses reviews that arrived during the lag
    once the cursor marches past their updateTime.
    """
    from datetime import timedelta

    base = datetime(2026, 11, 9, 10, 0, tzinfo=timezone.utc)
    assert reviews_worker._fetch_cursor(base) == base - timedelta(minutes=15)
    assert reviews_worker._fetch_cursor(None) is None


@pytest.mark.asyncio
async def test_backoff_skip_leaves_poll_cursor_untouched(db, channel_id, config_id, monkeypatch):
    """A skipped pass must not move last_polled_at.

    Regression: the release path used to stamp the cursor on every pass, so
    a health-backoff skip moved the window past reviews Google had not
    returned yet — later passes filtered them out forever.
    """
    import asyncio
    import json
    from datetime import timedelta

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    factory = async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("app.database.async_session", factory)

    now = datetime.now(timezone.utc)
    frozen = now - timedelta(hours=1)
    config = await db.get(AutoReplyConfig, config_id)
    config.last_polled_at = frozen
    channel = await db.get(Channel, channel_id)
    meta = json.loads(channel.metadata_json or "{}")
    meta["health"] = {
        "backoff_until": (now + timedelta(hours=1)).isoformat(),
        "consecutive_failures": 3,
    }
    channel.metadata_json = json.dumps(meta)
    await db.commit()

    async def _claim(session, config_id_arg, last_polled_at):
        return True

    monkeypatch.setattr(reviews_worker, "_claim_channel", _claim)
    # NOTE: _release_channel is deliberately NOT patched — the real one must
    # only clear the lock, never stamp the cursor.

    stats = await reviews_worker._poll_one_channel(
        channel_id, config_id, asyncio.Semaphore(1)
    )

    assert stats["channels"] == 0
    await db.refresh(config)
    # SQLite drops tzinfo on round-trip; compare instants, not tz-awareness.
    assert config.last_polled_at.replace(tzinfo=None) == frozen.replace(tzinfo=None)


@pytest.mark.asyncio
async def test_successful_poll_advances_cursor(db, channel_id, config_id, monkeypatch):
    """A real fetch must move last_polled_at forward to ~now."""
    import asyncio

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    factory = async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr("app.database.async_session", factory)

    before = datetime.now(timezone.utc)
    config = await db.get(AutoReplyConfig, config_id)
    config.last_polled_at = before
    await db.commit()

    async def _claim(session, config_id_arg, last_polled_at):
        return True

    async def _process(session, channel, config):
        return {"reviews": 1, "replied": 0, "queued": 1, "skipped": 0, "adopted": 0, "errors": 0}

    monkeypatch.setattr(reviews_worker, "_claim_channel", _claim)
    monkeypatch.setattr(reviews_worker, "_is_in_health_backoff", lambda channel, now: False)
    monkeypatch.setattr(reviews_worker, "process_channel", _process)

    stats = await reviews_worker._poll_one_channel(
        channel_id, config_id, asyncio.Semaphore(1)
    )

    assert stats["channels"] == 1
    await db.refresh(config)
    assert config.last_polled_at is not None
    assert config.last_polled_at.replace(tzinfo=None) >= before.replace(tzinfo=None)

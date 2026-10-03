"""Consumer event-guard tests + review edit detection (content comparison)."""
import asyncio

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.analytics import consumer
from app.modules.analytics.consumer import _process_message
from conftest import TEST_ENGINE


def test_process_message_handles_malformed():
    asyncio.run(_process_message(None))
    asyncio.run(_process_message(b"not json"))
    asyncio.run(_process_message(b'{"event_type": "unknown.thing", "payload": {}}'))


def test_process_message_handles_empty():
    asyncio.run(_process_message(b'{"event_type": "review.enriched", "payload": {}}'))


def _test_session_factory():
    """Session factory bound to the test engine (consumer opens its own)."""
    return async_sessionmaker(TEST_ENGINE, class_=AsyncSession, expire_on_commit=False)


@pytest.mark.asyncio
async def test_discovered_flags_edited_review_and_notifies_once(
    db, user_id, channel_id, monkeypatch
):
    """Content change on an enriched review: snapshot + flag + one notification.

    A replay of the identical payload must stay idempotent — no duplicate
    flag refresh notification and no second re-enrichment.
    """
    from app.modules.analytics.models import ReviewInsight
    from app.modules.notifications.models import Notification

    db.add(ReviewInsight(
        id="ins-edit-1", user_id=user_id, channel_id=channel_id,
        review_id="gg-edit-1", rating=5, review_text="Perfect!",
        reviewer_name="Sara", sentiment="positive", sentiment_score=0.8,
        topics=[], products=[], problems=[], enrichment_status="done",
    ))
    await db.commit()

    async def _fake_enrich(rating, text, reviewer_name, tenant_id=None):
        return {"sentiment": "negative", "sentiment_score": -0.6,
                "topics": [], "products": [], "problems": []}

    events: list[str] = []

    async def _fake_enqueue(event_type, payload, topic="review-events"):
        events.append(event_type)
        return "evt"

    monkeypatch.setattr(consumer, "async_session", _test_session_factory())
    monkeypatch.setattr(consumer, "enrich_review", _fake_enrich)
    monkeypatch.setattr(consumer, "enqueue_event", _fake_enqueue)

    payload = {
        "user_id": user_id, "channel_id": channel_id, "review_id": "gg-edit-1",
        "rating": 2, "text": "Actually broke after a week", "reviewer_name": "Sara",
        "review_updated_at": None,
    }
    await consumer._handle_discovered(payload)

    row = (await db.execute(
        select(ReviewInsight).where(ReviewInsight.review_id == "gg-edit-1")
    )).scalar_one()
    assert row.rating == 2
    assert row.edited is True
    assert row.previous_rating == 5
    assert row.previous_review_text == "Perfect!"
    assert row.sentiment == "negative"  # re-enriched on the new content
    assert "review.enriched" in events

    notes = (await db.execute(
        select(Notification).where(Notification.type == "review_edited")
    )).scalars().all()
    assert len(notes) == 1
    assert "★5 → ★2" in notes[0].title
    assert notes[0].data["review_id"] == "gg-edit-1"
    assert notes[0].href == "/dashboard/reviews?tab=edited"

    # Identical replay: idempotent — no second notification, flag untouched.
    await consumer._handle_discovered(payload)
    notes = (await db.execute(
        select(Notification).where(Notification.type == "review_edited")
    )).scalars().all()
    assert len(notes) == 1
    assert row.edited is True


@pytest.mark.asyncio
async def test_discovered_backfill_is_not_an_edit(db, user_id, channel_id, monkeypatch):
    """A text going from empty to filled must not be treated as a reviewer
    edit — no flag, no notification (backfilling gaps is the sync's job,
    the consumer just must not mistake it for an edit)."""
    from app.modules.analytics.models import ReviewInsight
    from app.modules.notifications.models import Notification

    db.add(ReviewInsight(
        id="ins-backfill-1", user_id=user_id, channel_id=channel_id,
        review_id="gg-bf-1", rating=4, review_text=None,
        reviewer_name="Omar", sentiment="neutral", sentiment_score=0.0,
        topics=[], products=[], problems=[], enrichment_status="done",
    ))
    await db.commit()

    async def _fake_enrich(rating, text, reviewer_name, tenant_id=None):
        return {"sentiment": "positive", "sentiment_score": 0.5,
                "topics": [], "products": [], "problems": []}

    async def _fake_enqueue(event_type, payload, topic="review-events"):
        return "evt"

    monkeypatch.setattr(consumer, "async_session", _test_session_factory())
    monkeypatch.setattr(consumer, "enrich_review", _fake_enrich)
    monkeypatch.setattr(consumer, "enqueue_event", _fake_enqueue)

    await consumer._handle_discovered({
        "user_id": user_id, "channel_id": channel_id, "review_id": "gg-bf-1",
        "rating": 4, "text": "Nice place", "reviewer_name": "Omar",
        "review_updated_at": None,
    })

    row = (await db.execute(
        select(ReviewInsight).where(ReviewInsight.review_id == "gg-bf-1")
    )).scalar_one()
    assert row.edited is False
    assert row.previous_review_text is None
    assert row.previous_rating is None
    notes = (await db.execute(
        select(Notification).where(Notification.type == "review_edited")
    )).scalars().all()
    assert notes == []


@pytest.mark.asyncio
async def test_replied_keeps_edit_flag_until_posted(db, user_id, channel_id, monkeypatch):
    """A queued (pending_approval) reply keeps the edit flag; only a posted
    reply — generated from the fresh content — clears it."""
    from datetime import datetime, timezone

    from app.modules.analytics.models import ReviewInsight

    db.add(ReviewInsight(
        id="ins-clear-1", user_id=user_id, channel_id=channel_id,
        review_id="gg-clear-1", rating=1, review_text="Updated: worse",
        reviewer_name="Sara", sentiment="negative", sentiment_score=-0.9,
        topics=[], products=[], problems=[], enrichment_status="done",
        edited=True, edited_at=datetime.now(timezone.utc),
        previous_rating=5, previous_review_text="Great!",
    ))
    await db.commit()

    async def _noop_rollup(channel_id, user_id, bucket_date):
        return None

    monkeypatch.setattr(consumer, "async_session", _test_session_factory())
    monkeypatch.setattr(consumer, "recompute_daily_rollup", _noop_rollup)

    base = {"user_id": user_id, "channel_id": channel_id, "review_id": "gg-clear-1"}

    await consumer._handle_replied({**base, "status": "pending_approval"})
    db.expire_all()
    row = (await db.execute(
        select(ReviewInsight).where(ReviewInsight.review_id == "gg-clear-1")
    )).scalar_one()
    assert row.replied is True
    assert row.edited is True
    assert row.previous_review_text == "Great!"

    await consumer._handle_replied({**base, "status": "posted"})
    db.expire_all()
    row = (await db.execute(
        select(ReviewInsight).where(ReviewInsight.review_id == "gg-clear-1")
    )).scalar_one()
    assert row.edited is False
    assert row.edited_at is None
    assert row.previous_rating is None
    assert row.previous_review_text is None


def test_merge_consecutive_folds_same_role_turns():
    """qwen3 on Groq returns an EMPTY 1-token completion for consecutive
    same-role turns (a customer firing "Hi / Bro what the hell / Hi"), so
    the history must be folded before it reaches the provider."""
    from app.modules.llm.providers.base import LLMMessage, merge_consecutive

    history = [
        LLMMessage(role="user", content="Hi"),
        LLMMessage(role="user", content="Bro what the hell"),
        LLMMessage(role="assistant", content="Hey!"),
        LLMMessage(role="assistant", content="What's up?"),
        LLMMessage(role="user", content="hi"),
    ]
    merged = merge_consecutive(history)

    assert [m.role for m in merged] == ["user", "assistant", "user"]
    assert merged[0].content == "Hi\nBro what the hell"
    assert merged[1].content == "Hey!\nWhat's up?"
    assert merged[2].content == "hi"
    # input is not mutated
    assert history[0].content == "Hi"
    assert merge_consecutive([]) == []

"""Consumer tenant isolation (B3): forged Kafka identities must not re-attribute rows."""
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.analytics import consumer
from conftest import TEST_ENGINE


def _test_session_factory():
    """Session factory bound to the test engine (consumer opens its own)."""
    return async_sessionmaker(TEST_ENGINE, class_=AsyncSession, expire_on_commit=False)


@pytest.mark.asyncio
async def test_discovered_forged_user_id_uses_channel_owner(db, user_id, channel_id, monkeypatch):
    """A forged payload user_id must NOT re-attribute the review (B3)."""
    from app.modules.analytics.models import ReviewInsight

    async def _fake_enrich(rating, text, reviewer_name, tenant_id=None):
        assert tenant_id == user_id  # enrichment runs in the owner's context
        return {"sentiment": "positive", "sentiment_score": 0.5,
                "topics": [], "products": [], "problems": []}

    async def _fake_enqueue(event_type, payload, topic="review-events"):
        return "evt"

    monkeypatch.setattr(consumer, "async_session", _test_session_factory())
    monkeypatch.setattr(consumer, "enrich_review", _fake_enrich)
    monkeypatch.setattr(consumer, "enqueue_event", _fake_enqueue)

    await consumer._handle_discovered({
        "user_id": "attacker-tenant", "channel_id": channel_id,
        "review_id": "gg-forge-1", "rating": 5, "text": "Great!",
        "reviewer_name": "Sara", "review_updated_at": None,
    })

    row = (await db.execute(
        select(ReviewInsight).where(ReviewInsight.review_id == "gg-forge-1")
    )).scalar_one()
    assert row.user_id == user_id


@pytest.mark.asyncio
async def test_discovered_unknown_channel_dropped(db, monkeypatch):
    """Events for channels with no DB row are dropped, never stored (B3)."""
    from app.modules.analytics.models import ReviewInsight

    async def _fake_enqueue(event_type, payload, topic="review-events"):
        raise AssertionError("must not emit for dropped events")

    monkeypatch.setattr(consumer, "async_session", _test_session_factory())
    monkeypatch.setattr(consumer, "enqueue_event", _fake_enqueue)

    await consumer._handle_discovered({
        "user_id": "anyone", "channel_id": "no-such-channel",
        "review_id": "gg-ghost-1", "rating": 5, "text": "Great!",
        "reviewer_name": "Sara", "review_updated_at": None,
    })

    rows = (await db.execute(
        select(ReviewInsight).where(ReviewInsight.review_id == "gg-ghost-1")
    )).scalars().all()
    assert rows == []

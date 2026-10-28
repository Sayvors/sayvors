"""A failed enrichment must be visible and retryable (D11).

The heuristic fallback used to be stored as a finished enrichment: the row
said "done", so the consumer treated every later copy of that review as an
idempotent replay and never asked the model again. A keyword guess was
remembered as the final answer.
"""
import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.analytics import consumer
from app.modules.analytics.models import ReviewInsight
from app.modules.channels.models import Channel

_CHANNEL_ID = "enrich-channel-0001"
_REVIEW_ID = "enrich-review-0001"


@pytest_asyncio.fixture
async def consumer_db(db, monkeypatch):
    """The consumer and the outbox open their own sessions; hand them the
    test session.

    A second engine here would outlive the test's event loop and fail the
    *next* test during garbage collection; the production engine would talk
    to the real Postgres instead of the test database.
    """
    from contextlib import asynccontextmanager

    from app.modules.outbox import service as outbox_service

    @asynccontextmanager
    async def _session():
        yield db

    monkeypatch.setattr(consumer, "async_session", _session)
    monkeypatch.setattr(outbox_service, "async_session", _session)
    yield db


@pytest.fixture
def payload(user_id):
    return {
        "channel_id": _CHANNEL_ID,
        "review_id": _REVIEW_ID,
        "rating": 2,
        "text": "the service was slow and the food was cold",
        "user_id": user_id,
    }


def _stub_llm(monkeypatch, result: dict):
    calls = {"enrich": 0}

    async def _enrich(*args, **kwargs):
        calls["enrich"] += 1
        return dict(result)

    async def _meaning(*args, **kwargs):
        return None

    monkeypatch.setattr(consumer, "enrich_review", _enrich)
    monkeypatch.setattr(consumer, "extract_meaning", _meaning)
    return calls


async def _seed_channel(db, user_id):
    db.add(
        Channel(
            id=_CHANNEL_ID,
            user_id=user_id,
            platform="google_reviews",
            platform_user_id="accounts/1",
            display_name="Shop",
            status="active",
        )
    )
    await db.commit()


@pytest.mark.asyncio
async def test_heuristic_fallback_is_recorded_as_failed(consumer_db, payload, user_id, monkeypatch):
    await _seed_channel(consumer_db, user_id)
    _stub_llm(
        monkeypatch,
        {
            "sentiment": "negative",
            "sentiment_score": -0.5,
            "topics": [],
            "products": [],
            "problems": [],
            "heuristic": True,
        },
    )

    await consumer._handle_discovered(payload)

    row = (
        await consumer_db.execute(
            select(ReviewInsight).where(ReviewInsight.review_id == _REVIEW_ID)
        )
    ).scalar_one()
    assert row.enrichment_status == "failed"
    # The guess is still stored - it beats an empty review while the model is down.
    assert row.sentiment == "negative"


@pytest.mark.asyncio
async def test_a_real_enrichment_is_recorded_as_done(consumer_db, payload, user_id, monkeypatch):
    await _seed_channel(consumer_db, user_id)
    _stub_llm(
        monkeypatch,
        {
            "sentiment": "negative",
            "sentiment_score": -0.5,
            "topics": [],
            "products": [],
            "problems": [],
            "heuristic": False,
        },
    )

    await consumer._handle_discovered(payload)

    row = (
        await consumer_db.execute(
            select(ReviewInsight).where(ReviewInsight.review_id == _REVIEW_ID)
        )
    ).scalar_one()
    assert row.enrichment_status == "done"


@pytest.mark.asyncio
async def test_a_failed_enrichment_is_retried_on_the_next_copy(consumer_db, payload, user_id, monkeypatch):
    """A failed row must not be treated as a finished, idempotent replay."""
    await _seed_channel(consumer_db, user_id)
    calls = _stub_llm(
        monkeypatch,
        {
            "sentiment": "neutral",
            "sentiment_score": 0.0,
            "topics": [],
            "products": [],
            "problems": [],
            "heuristic": True,
        },
    )

    await consumer._handle_discovered(payload)
    await consumer._handle_discovered(payload)

    assert calls["enrich"] == 2, "the second copy was skipped as a replay"

"""Analytics pulse cards: reputation + who-is-waiting aggregates."""
import json
from datetime import datetime, timedelta, timezone

import pytest

from app.modules.analytics.models import ChannelDailyMetric, ReviewInsight
from app.modules.analytics.pulse import get_pulse
from app.modules.channels.models import Channel


async def _seed_channel(
    db,
    user_id,
    channel_id,
    platform="google_reviews",
    last_success_at=None,
    metadata_json=None,
):
    if metadata_json is None:
        meta = {}
        if last_success_at is not None:
            meta["health"] = {"last_success_at": last_success_at.isoformat()}
        metadata_json = json.dumps(meta)
    db.add(Channel(
        id=channel_id, user_id=user_id, platform=platform,
        platform_user_id=f"acct-{channel_id}", display_name=channel_id,
        status="active", metadata_json=metadata_json,
    ))


async def _seed_review(db, user_id, channel_id, idx, rating, replied, days_ago=0, skipped=False, removed=False):
    when = datetime.now(timezone.utc) - timedelta(days=days_ago)
    db.add(ReviewInsight(
        id=f"{channel_id}-ins-{idx}", user_id=user_id, channel_id=channel_id,
        review_id=f"{channel_id}-r{idx}", rating=rating,
        review_text="ok", reviewer_name=f"Guest {idx}",
        sentiment="positive" if rating >= 4 else "negative",
        sentiment_score=0.8 if rating >= 4 else -0.6,
        topics=[], products=[], problems=[], enrichment_status="done",
        replied=replied, skipped=skipped,
        review_updated_at=when,
        removed_at=when if removed else None,
    ))


@pytest.mark.asyncio
async def test_pulse_reputation_and_waiting(db, user_id):
    synced_at = datetime.now(timezone.utc) - timedelta(hours=2)
    await _seed_channel(db, user_id, "ch-pulse", last_success_at=synced_at)
    # Current period: 4 reviews (3 replied), avg 4.5. Prior: 2 reviews avg 4.0.
    await _seed_review(db, user_id, "ch-pulse", 1, 5, True, days_ago=1)
    await _seed_review(db, user_id, "ch-pulse", 2, 5, True, days_ago=2)
    await _seed_review(db, user_id, "ch-pulse", 3, 4, True, days_ago=3)
    await _seed_review(db, user_id, "ch-pulse", 4, 4, False, days_ago=4)
    await _seed_review(db, user_id, "ch-pulse", 5, 4, True, days_ago=40)
    await _seed_review(db, user_id, "ch-pulse", 6, 4, True, days_ago=41)
    # Excluded: removed and skipped rows never count as awaiting.
    await _seed_review(db, user_id, "ch-pulse", 7, 1, False, days_ago=5, removed=True)
    await _seed_review(db, user_id, "ch-pulse", 8, 1, False, days_ago=6, skipped=True)

    today = datetime.now(timezone.utc).date()
    db.add(ChannelDailyMetric(
        id="cdm-1", user_id=user_id, channel_id="ch-pulse", date=today,
        messages_in=10, messages_out=8, conversations_in=5, conversations_replied=4,
        frt_samples=[600, 900, 1200],  # 10 / 15 / 20 min
        unanswered_open=3, oldest_unanswered_seconds=7200,
        computed_at=datetime.now(timezone.utc),
    ))
    await db.commit()

    out = await get_pulse(db, user_id, None, 30)

    rep = out["reputation"]
    assert rep["new_reviews"] == 4
    assert rep["avg_rating"] == 4.5
    assert rep["rating_delta"] == 0.5
    assert rep["new_reviews_delta_pct"] == 100.0
    assert rep["response_rate"] == 75.0
    assert rep["awaiting_reply"] == 1  # only the live, unskipped unreplied row
    assert rep["oldest_wait_days"] == 4
    assert rep["sources"] == [{"platform": "google_reviews", "count": 4}]
    assert rep["last_synced_at"] == synced_at

    waiting = out["waiting"]
    assert waiting["unanswered_texts"] == 3
    assert waiting["median_first_response_seconds"] == 900
    assert waiting["waiting_over_1h"] == 1
    assert waiting["oldest_unanswered_seconds"] == 7200
    assert waiting["missed_calls"] is None
    assert waiting["missed_calls_available"] is False

    # Location league: one channel, plus a below-threshold flag.
    assert len(out["locations"]) == 1
    loc = out["locations"][0]
    assert loc["channel_id"] == "ch-pulse"
    assert loc["new_reviews"] == 4
    assert loc["avg_rating"] == 4.5
    assert loc["response_rate"] == 75.0
    assert loc["unanswered"] == 1
    assert loc["below_threshold"] is False

    # Needs attention: outstanding reviews (oldest 4d -> high) + waiting >1h.
    kinds = {a["kind"] for a in out["attention"]}
    assert "reviews" in kinds
    assert "messages" in kinds
    assert out["one_thing"] is None  # no problem data seeded


@pytest.mark.asyncio
async def test_pulse_channel_scope(db, user_id):
    await _seed_channel(db, user_id, "ch-a")
    await _seed_channel(db, user_id, "ch-b", platform="facebook")
    await _seed_review(db, user_id, "ch-a", 1, 5, True, days_ago=1)
    await _seed_review(db, user_id, "ch-b", 2, 1, False, days_ago=1)
    await db.commit()

    out = await get_pulse(db, user_id, "ch-a", 30)
    assert out["reputation"]["new_reviews"] == 1
    assert out["reputation"]["awaiting_reply"] == 0
    assert out["reputation"]["sources"] == [{"platform": "google_reviews", "count": 1}]


@pytest.mark.asyncio
async def test_pulse_one_thing_and_low_rating_location(db, user_id):
    await _seed_channel(db, user_id, "ch-low")
    now = datetime.now(timezone.utc)
    # Current period: two "waiting time" complaints; prior: one.
    for i, days_ago in enumerate((1, 2, 40)):
        db.add(ReviewInsight(
            id=f"ch-low-ins-{i}", user_id=user_id, channel_id="ch-low",
            review_id=f"ch-low-r{i}", rating=2, review_text="long wait",
            reviewer_name=f"Guest {i}", sentiment="negative", sentiment_score=-0.8,
            topics=[], products=[],
            problems=[{"name": "long waiting time", "severity": "high"}],
            enrichment_status="done", replied=False,
            review_updated_at=now - timedelta(days=days_ago),
        ))
    await db.commit()

    out = await get_pulse(db, user_id, None, 30)
    loc = out["locations"][0]
    assert loc["avg_rating"] == 2.0
    assert loc["below_threshold"] is True

    assert out["one_thing"] is not None
    assert out["one_thing"]["category"] == "waiting_time"
    assert out["one_thing"]["mentions"] == 2
    assert out["one_thing"]["trend_pct"] == 100.0


@pytest.mark.asyncio
async def test_pulse_last_synced_uses_health_not_review_arrival(db, user_id):
    synced_at = datetime.now(timezone.utc) - timedelta(hours=2)
    await _seed_channel(db, user_id, "ch-quiet", last_success_at=synced_at)
    # The newest review is 35 days old, but the poller succeeded two hours
    # ago. "Synced 35d ago" would blame the sync for a quiet review week.
    await _seed_review(db, user_id, "ch-quiet", 1, 5, True, days_ago=35)
    await db.commit()

    out = await get_pulse(db, user_id, None, 30)

    assert out["reputation"]["last_synced_at"] == synced_at
    assert "sync" not in {a["kind"] for a in out["attention"]}


@pytest.mark.asyncio
async def test_pulse_flags_stale_health_even_when_reviews_are_fresh(db, user_id):
    stale_at = datetime.now(timezone.utc) - timedelta(days=3)
    await _seed_channel(db, user_id, "ch-stale", last_success_at=stale_at)
    # A review arrived today, so max(review_updated_at) would hide the fact
    # that the poller itself has not succeeded in three days.
    await _seed_review(db, user_id, "ch-stale", 1, 5, True, days_ago=0)
    await db.commit()

    out = await get_pulse(db, user_id, None, 30)

    assert out["reputation"]["last_synced_at"] == stale_at
    sync_cards = [a for a in out["attention"] if a["kind"] == "sync"]
    assert len(sync_cards) == 1
    assert sync_cards[0]["title"] == "Review sync is stale"
    assert sync_cards[0]["detail"] == "oldest success 3d ago"


@pytest.mark.asyncio
async def test_pulse_sync_health_is_channel_scoped(db, user_id):
    now = datetime.now(timezone.utc)
    fresh_at = now - timedelta(hours=1)
    stale_at = now - timedelta(days=2)
    await _seed_channel(db, user_id, "ch-fresh", last_success_at=fresh_at)
    await _seed_channel(db, user_id, "ch-stale", last_success_at=stale_at)
    await db.commit()

    fresh = await get_pulse(db, user_id, "ch-fresh", 30)
    assert fresh["reputation"]["last_synced_at"] == fresh_at
    assert "sync" not in {a["kind"] for a in fresh["attention"]}

    stale = await get_pulse(db, user_id, "ch-stale", 30)
    assert stale["reputation"]["last_synced_at"] == stale_at
    assert {a["kind"] for a in stale["attention"]} == {"sync"}

    # Unfiltered, the headline is the newest successful poll, while the card
    # still names the location that has stopped succeeding.
    all_channels = await get_pulse(db, user_id, None, 30)
    assert all_channels["reputation"]["last_synced_at"] == fresh_at
    sync_card = next(a for a in all_channels["attention"] if a["kind"] == "sync")
    assert sync_card["title"] == "1 of 2 locations haven't synced in 24h"


@pytest.mark.asyncio
async def test_pulse_tolerates_malformed_health_metadata(db, user_id):
    await _seed_channel(db, user_id, "ch-bad-json", metadata_json="not-json")
    await _seed_channel(
        db,
        user_id,
        "ch-bad-date",
        metadata_json=json.dumps({"health": {"last_success_at": "not-a-date"}}),
    )
    await db.commit()

    out = await get_pulse(db, user_id, None, 30)

    assert out["reputation"]["last_synced_at"] is None
    assert "sync" not in {a["kind"] for a in out["attention"]}


@pytest.mark.asyncio
async def test_pulse_empty_tenant(db, user_id):
    out = await get_pulse(db, user_id, None, 30)
    rep = out["reputation"]
    assert rep["new_reviews"] == 0
    assert rep["avg_rating"] == 0.0
    assert rep["response_rate"] == 0.0
    assert rep["awaiting_reply"] == 0
    assert rep["rating_delta"] is None
    assert rep["new_reviews_delta_pct"] is None
    assert rep["last_synced_at"] is None
    assert out["waiting"]["unanswered_texts"] == 0
    assert out["waiting"]["median_first_response_seconds"] is None

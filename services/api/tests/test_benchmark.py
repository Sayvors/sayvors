"""Branch-vs-branch benchmark tests (service level)."""
from datetime import datetime, timezone

import pytest

from app.modules.analytics import benchmark
from app.modules.analytics.models import ReviewInsight
from app.modules.channels.models import Channel


async def _seed_branch(db, user_id, channel_id, name, reviews):
    db.add(Channel(
        id=channel_id, user_id=user_id, platform="google_reviews",
        platform_user_id=f"demo-{channel_id}", display_name=name,
        status="active", metadata_json="{}",
    ))
    for i, (rating, sentiment, replied) in enumerate(reviews):
        db.add(ReviewInsight(
            id=f"{channel_id}-ins-{i}", user_id=user_id, channel_id=channel_id,
            review_id=f"{channel_id}-r{i}", rating=rating,
            review_text="Tasty!" if rating >= 4 else "Too slow.",
            reviewer_name=f"Guest {i}", sentiment=sentiment,
            sentiment_score=0.9 if sentiment == "positive" else -0.7,
            topics=[], products=[], problems=[],
            enrichment_status="done", replied=replied,
            review_updated_at=datetime.now(timezone.utc),
        ))
    await db.commit()


@pytest.mark.asyncio
async def test_branch_ranking_leader_and_attention(db, user_id):
    await _seed_branch(db, user_id, "ch-good", "Al Malqa",
                       [(5, "positive", True), (5, "positive", True), (4, "positive", True)])
    await _seed_branch(db, user_id, "ch-bad", "Makkah",
                       [(2, "negative", False), (2, "negative", False)])

    out = await benchmark.get_benchmark(db, user_id, None, 30)

    assert len(out["branches"]) == 2
    assert out["branches"][0]["name"] == "Al Malqa"
    assert out["branches"][0]["rank"] == 1
    assert out["branches"][1]["rank"] == 2
    assert out["branches"][0]["avg_rating"] == 4.67
    assert out["leader"]["name"] == "Al Malqa"
    assert len(out["leader"]["reasons"]) > 0
    assert out["needs_attention"]["name"] == "Makkah"
    assert any("4.0" in r for r in out["needs_attention"]["reasons"])
    assert any(r["name"] == "Makkah" and r["priority"] == "high" for r in out["recommendations"])
    assert any(r["priority"] == "win" for r in out["recommendations"])


@pytest.mark.asyncio
async def test_empty_branch_excluded_from_leader_race(db, user_id):
    await _seed_branch(db, user_id, "ch-full", "Al Malqa", [(5, "positive", True)])
    db.add(Channel(
        id="ch-empty", user_id=user_id, platform="google_reviews",
        platform_user_id="demo-empty", display_name="Malaz",
        status="active", metadata_json="{}",
    ))
    await db.commit()

    out = await benchmark.get_benchmark(db, user_id, None, 30)

    assert len(out["branches"]) == 2
    assert out["leader"]["name"] == "Al Malqa"
    # Single rated branch → nudge to connect more, not a fake rivalry
    assert out["needs_attention"] is None
    assert any("branch-vs-branch" in r["text"] for r in out["recommendations"])

"""Branch-vs-branch benchmark tests (service level)."""
import json
from datetime import datetime, timezone

import pytest

from app.modules.analytics import benchmark
from app.modules.analytics.models import ReviewInsight
from app.modules.channels.models import Channel
from app.modules.users.models import User


async def _seed_branch(
    db, user_id, channel_id, name, reviews, address=None, category=None
):
    meta = {}
    if address:
        meta["address"] = address
    if category:
        meta["category"] = category
    db.add(Channel(
        id=channel_id, user_id=user_id, platform="google_reviews",
        platform_user_id=f"demo-{channel_id}", display_name=name,
        status="active", metadata_json=json.dumps(meta),
        listing_key=channel_id,
        # Native Google peers have OAuth credentials; the benchmark excludes
        # tokenless seeded/demo rows from the market cohort.
        access_token="test-token", refresh_token="test-refresh",
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
async def test_benchmark_gap_to_45_and_recency(db, user_id):
    # Three live reviews at 4 stars: avg 4.0. X = ceil(3*(9-8)) = 3.
    await _seed_branch(db, user_id, "ch-gap", "Gap Branch",
                       [(4, "positive", True), (4, "positive", True), (4, "positive", True)])
    out = await benchmark.get_benchmark(db, user_id, None, 30)

    gap = out["gap_to_target"]
    assert gap["target"] == 4.5
    assert gap["current_rating"] == 4.0
    assert gap["current_reviews"] == 3
    assert gap["five_star_needed"] == 3
    assert "4.5" in gap["math"]

    rec = out["recency"]
    assert rec["total"] == 3
    assert rec["recent_90"] == 3
    assert rec["my_pct"] == 100.0


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


def _user(db, uid, email, business_type=None):
    db.add(User(id=uid, first_name="T", last_name="U", email=email,
                password_hash="x", business_type=business_type))


async def _peer(db, uid, cid, name, address, rating, reviews, category):
    await _seed_branch(
        db, uid, cid, name,
        [(rating, "positive", True)] * reviews,
        address=address, category=category,
    )


@pytest.mark.asyncio
async def test_cohort_ranks_tenants_not_demo_account(db):
    """Native Google channels ARE the competitor set: same city + category
    tenants rank together, self excluded, my rank computed."""
    _user(db, "me", "me@x.com", "restaurant")
    _user(db, "u2", "u2@x.com", "restaurant")
    _user(db, "u3", "u3@x.com", "salon")  # different category, same city
    await _peer(db, "me", "ch-me", "My Place", "RIYADH Al Malqa", 5, 4, "Restaurant")
    await _peer(db, "u2", "ch-u2", "Rival Diner", "RIYADH Olaya", 4, 6, "Restaurant")
    await _peer(db, "u3", "ch-u3", "Other Salon", "RIYADH Malaz", 5, 8, "Salon")

    out = await benchmark.get_benchmark(db, "me", None, 30)
    cohort = out["cohort"]
    assert cohort["scope"] == "city_category"
    assert cohort["count"] == 1
    assert cohort["competitors"][0]["name"] == "Rival Diner"
    assert cohort["competitors"][0]["is_you"] is False
    assert all(e["name"] != "Other Salon" for e in out["market"])
    assert out["my_rank"] == 1
    assert "#None" not in out["benchmark_text"]


@pytest.mark.asyncio
async def test_cohort_widens_when_category_empty(db):
    _user(db, "me", "me@x.com", "restaurant")
    _user(db, "u2", "u2@x.com", "salon")
    await _peer(db, "me", "ch-me", "My Place", "RIYADH Al Malqa", 5, 3, "Restaurant")
    await _peer(db, "u2", "ch-u2", "Other Salon", "RIYADH Malaz", 5, 5, "Salon")

    out = await benchmark.get_benchmark(db, "me", None, 30)
    assert out["cohort"]["scope"] == "city"
    assert out["cohort"]["count"] == 1


@pytest.mark.asyncio
async def test_cohort_empty_first_tenant(db):
    _user(db, "solo", "solo@x.com", "restaurant")
    await _peer(db, "solo", "ch-solo", "Solo Spot", "RIYADH Malqa", 5, 3, "Restaurant")

    out = await benchmark.get_benchmark(db, "solo", None, 30)
    assert out["cohort"]["count"] == 0
    # The tenant has one branch, so it is rank 1 in its own (peer-less) market;
    # the UI hides the rank until the peer cohort reaches three businesses.
    assert out["my_rank"] == 1
    assert "first" in out["benchmark_text"]


@pytest.mark.asyncio
async def test_parse_city():
    assert benchmark._parse_city("RIYADH Al Malqa Dist.") == "RIYADH"
    assert benchmark._parse_city("Jeddah, Olaya") == "JEDDAH"
    assert benchmark._parse_city(None) is None
    assert benchmark._parse_city("!!") is None


@pytest.mark.asyncio
async def test_cohort_ranks_me_against_tenants(db, user_id):
    """My 5★ branch outranks the 4★ rival: rank 1, leader text."""
    _user(db, user_id, "mine@x.com", "restaurant")
    await _peer(db, user_id, "ch-mine", "My Place", "RIYADH Malqa", 5, 2, "Restaurant")
    _user(db, "u2", "u2@x.com", "restaurant")
    await _peer(db, "u2", "ch-u2", "Rival Diner", "RIYADH Olaya", 4, 5, "Restaurant")

    out = await benchmark.get_benchmark(db, user_id, None, 30)
    assert out["my_rank"] == 1
    assert out["market"][0]["is_you"] is True
    assert out["market"][1]["name"] == "Rival Diner"
    assert "leading the pack" in out["benchmark_text"]

"""Branch-vs-branch benchmark tests (service level)."""
from datetime import datetime, timezone

import pytest

from app.modules.analytics import benchmark
from app.modules.analytics.models import ReviewInsight
from app.modules.channels.models import Channel
from app.modules.localith.models import LocalithConnection
from app.modules.users.models import User


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


def _user(db, uid, email, business_type=None):
    db.add(User(id=uid, first_name="T", last_name="U", email=email,
                password_hash="x", business_type=business_type))


def _conn(db, uid, lid, name, address, rating, reviews):
    db.add(LocalithConnection(
        user_id=uid, listing_id=lid, listing_name=name, address=address,
        total_reviews=reviews, average_rating=rating,
    ))


@pytest.mark.asyncio
async def test_cohort_ranks_tenants_not_demo_account(db):
    """Tenants ARE the competitor set: same city + category tenants rank
    together, self excluded, my rank computed."""
    _user(db, "me", "me@x.com", "restaurant")
    _user(db, "u2", "u2@x.com", "restaurant")
    _user(db, "u3", "u3@x.com", "salon")  # different category, same city
    _conn(db, "me", "l-me", "My Place", "RIYADH Al Malqa", 4.5, 10)
    _conn(db, "u2", "l-u2", "Rival Diner", "RIYADH Olaya", 4.8, 40)
    _conn(db, "u3", "l-u3", "Other Salon", "RIYADH Malaz", 5.0, 100)
    await db.commit()

    out = await benchmark.get_benchmark(db, "me", None, 30)
    cohort = out["cohort"]
    assert cohort["scope"] == "city_category"
    assert cohort["count"] == 1
    assert cohort["competitors"][0]["name"] == "Rival Diner"
    assert cohort["competitors"][0]["is_you"] is False
    assert all(e["name"] != "Other Salon" for e in out["market"])
    # No branches of mine yet: honest unranked state, no "#None".
    assert out["my_rank"] is None
    assert "connect a branch" in out["benchmark_text"]
    assert "#None" not in out["benchmark_text"]
@pytest.mark.asyncio
async def test_cohort_widens_when_category_empty(db):
    _user(db, "me", "me@x.com", "restaurant")
    _user(db, "u2", "u2@x.com", "salon")
    _conn(db, "me", "l-me", "My Place", "RIYADH Al Malqa", 4.5, 10)
    _conn(db, "u2", "l-u2", "Other Salon", "RIYADH Malaz", 5.0, 100)
    await db.commit()

    out = await benchmark.get_benchmark(db, "me", None, 30)
    assert out["cohort"]["scope"] == "city"
    assert out["cohort"]["count"] == 1


@pytest.mark.asyncio
async def test_cohort_empty_first_tenant(db):
    _user(db, "solo", "solo@x.com", "restaurant")
    _conn(db, "solo", "l-s", "Solo Spot", "RIYADH Malqa", 5.0, 3)
    await db.commit()

    out = await benchmark.get_benchmark(db, "solo", None, 30)
    assert out["cohort"]["count"] == 0
    assert out["my_rank"] is None
    assert "first" in out["benchmark_text"]


@pytest.mark.asyncio
async def test_parse_city():
    assert benchmark._parse_city("RIYADH Al Malqa Dist.") == "RIYADH"
    assert benchmark._parse_city("Jeddah, Olaya") == "JEDDAH"
    assert benchmark._parse_city(None) is None
    assert benchmark._parse_city("!!") is None


@pytest.mark.asyncio
async def test_cohort_ranks_me_against_tenants(db, user_id):
    """My 5.0★ branch outranks the 4.8 rival: rank 1, leader text."""
    _user(db, user_id, "mine@x.com", "restaurant")
    db.add(LocalithConnection(
        user_id=user_id, listing_id="l-mine", listing_name="My Place",
        address="RIYADH Malqa", total_reviews=10, average_rating=5.0,
    ))
    await _seed_branch(db, user_id, "ch-mine", "My Place",
                       [(5, "positive", True), (5, "positive", True)])
    _user(db, "u2", "u2@x.com", "restaurant")
    _conn(db, "u2", "l-u2", "Rival Diner", "RIYADH Olaya", 4.8, 40)
    await db.commit()

    out = await benchmark.get_benchmark(db, user_id, None, 30)
    assert out["my_rank"] == 1
    assert out["market"][0]["is_you"] is True
    assert out["market"][1]["name"] == "Rival Diner"
    assert "leading the pack" in out["benchmark_text"]

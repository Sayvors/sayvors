"""Insights dashboard cards: themes, change, location sentiment, summary, actions."""
from datetime import datetime, timedelta, timezone

import pytest

from app.modules.analytics.insights_cards import get_insights_cards
from app.modules.analytics.models import LocationIssue, ReviewInsight
from app.modules.channels.models import Channel


async def _seed(db, user_id):
    db.add(Channel(
        id="ch-dt", user_id=user_id, platform="google_reviews",
        platform_user_id="acct-dt", display_name="Downtown", status="active", metadata_json="{}",
    ))
    db.add(Channel(
        id="ch-ws", user_id=user_id, platform="google_reviews",
        platform_user_id="acct-ws", display_name="Westside", status="active", metadata_json="{}",
    ))
    now = datetime.now(timezone.utc)

    def review(i, cid, rating, days_ago, topics, problems, text, replied=True):
        db.add(ReviewInsight(
            id=f"{cid}-r{i}", user_id=user_id, channel_id=cid, review_id=f"{cid}-rid{i}",
            rating=rating, review_text=text, reviewer_name=f"Guest {i}",
            sentiment="positive" if rating >= 4 else "negative",
            sentiment_score=0.8 if rating >= 4 else -0.7,
            topics=topics, products=[], problems=problems,
            enrichment_status="done", replied=replied,
            review_updated_at=now - timedelta(days=days_ago),
        ))

    # Current period, Downtown: service praise + wait complaints.
    review(1, "ch-dt", 5, 2, [{"name": "service", "sentiment": "positive"}], [], "Great staff!")
    review(2, "ch-dt", 2, 3, [{"name": "waiting time", "sentiment": "negative"}],
           [{"name": "long waiting time", "severity": "high"}], "Waited 40 minutes.")
    review(3, "ch-dt", 1, 4, [{"name": "waiting time", "sentiment": "negative"}],
           [{"name": "long waiting time", "severity": "high"}], "Waited forever.")
    # Prior week, Downtown: one low review.
    review(4, "ch-dt", 1, 10, [{"name": "waiting time", "sentiment": "negative"}],
           [{"name": "long waiting time", "severity": "medium"}], "Slow.")
    # Westside: praise only.
    review(5, "ch-ws", 5, 1, [{"name": "service", "sentiment": "positive"}], [], "Lovely team.")

    db.add(LocationIssue(
        id="issue-1", user_id=user_id, channel_id="ch-dt", subject="speed_waiting",
        review_count=3, negative_count=2, avg_rating=1.5,
        evidence=[], title="Fix the wait at Downtown", detail="Add a host on weekends.",
        status="open",
    ))
    await db.commit()


@pytest.mark.asyncio
async def test_insights_cards_shape_and_values(db, user_id):
    await _seed(db, user_id)
    out = await get_insights_cards(db, user_id, None, 30)

    themes = {t["name"]: t for t in out["top_themes"]}
    assert "waiting time" in themes
    assert themes["waiting time"]["negative"] == 3
    assert themes["waiting time"]["quote"] in ("Waited 40 minutes.", "Waited forever.", "Slow.")
    assert themes["waiting time"]["top_location"] == "Downtown"  # concentrated there

    changed = out["what_changed"]
    assert changed["low_reviews"] == 2          # current 7d
    assert changed["prior_low_reviews"] == 1    # prior 7d
    assert changed["theme"] == "long waiting time"
    assert changed["location"] == "Downtown"

    locations = {l["name"]: l for l in out["sentiment_by_location"]}
    assert locations["Downtown"]["avg_rating"] == pytest.approx(2.25, abs=0.01)
    assert locations["Downtown"]["top_negative_theme"] == "long waiting time"
    assert locations["Westside"]["avg_rating"] == 5.0

    summary = out["summary"]
    assert summary["review_count"] == 5
    assert summary["confidence"] == "low"
    assert summary["source"] == "data"
    assert any(b["n"] == 3 for b in summary["bullets"])

    assert len(out["action_plan"]) == 1
    assert out["action_plan"][0]["title"] == "Fix the wait at Downtown"
    assert out["action_plan"][0]["status"] == "open"


@pytest.mark.asyncio
async def test_insights_cards_channel_scope(db, user_id):
    await _seed(db, user_id)
    out = await get_insights_cards(db, user_id, "ch-ws", 30)
    assert out["summary"]["review_count"] == 1
    assert [l["name"] for l in out["sentiment_by_location"]] == ["Westside"]
    assert out["action_plan"] == []

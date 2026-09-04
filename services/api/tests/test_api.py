"""API integration tests: analytics overview, reply workflow, config."""
import pytest

from app.modules.channels.models import ReviewReply


@pytest.mark.asyncio
async def test_overview_empty(client):
    r = client.get("/api/v1/analytics/overview?days=30")
    assert r.status_code == 200
    body = r.json()
    assert body["total_reviews"] == 0
    assert body["avg_rating"] == 0.0
    assert body["response_rate"] == 0.0
    assert body["reputation_score"] == 10  # neutral baseline
    assert body["health_score"] == 10


@pytest.mark.asyncio
async def test_overview_with_data(client, db, channel_id, user_id):
    from datetime import datetime, timezone

    from app.modules.analytics.models import ReviewInsight

    db.add(ReviewInsight(
        id="ins-1", user_id=user_id, channel_id=channel_id, review_id="r1",
        rating=5, review_text="Great!", reviewer_name="A", sentiment="positive",
        sentiment_score=0.9, topics=[], products=[], problems=[],
        enrichment_status="done", replied=True,
        review_updated_at=datetime.now(timezone.utc),
    ))
    await db.commit()
    r = client.get("/api/v1/analytics/overview?days=30")
    body = r.json()
    assert body["total_reviews"] == 1
    assert body["avg_rating"] == 5.0
    assert body["sentiment"]["positive"] == 1
    assert body["response_rate"] == 100.0


@pytest.mark.asyncio
async def test_timeseries_empty(client):
    r = client.get("/api/v1/analytics/timeseries?days=30")
    assert r.status_code == 200
    assert r.json()["points"] == []


@pytest.mark.asyncio
async def test_insights_list_empty(client):
    r = client.get("/api/v1/analytics/reviews/insights")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 0
    assert body["items"] == []


@pytest.mark.asyncio
async def test_insights_filter_by_sentiment(client, db, channel_id, user_id):
    from datetime import datetime, timezone

    from app.modules.analytics.models import ReviewInsight

    for i, (sentiment, text) in enumerate([
        ("positive", "Great food!"),
        ("negative", "Slow service, rude staff."),
    ]):
        db.add(ReviewInsight(
            id=f"ins-{i}", user_id=user_id, channel_id=channel_id, review_id=f"r{i}",
            rating=5 if sentiment == "positive" else 1, review_text=text, reviewer_name="A",
            sentiment=sentiment, sentiment_score=0.9 if sentiment == "positive" else -0.9,
            topics=[], products=[], problems=[], enrichment_status="done", replied=False,
            review_updated_at=datetime.now(timezone.utc),
        ))
    await db.commit()

    r = client.get("/api/v1/analytics/reviews/insights?sentiment=negative")
    assert r.json()["total"] == 1
    assert r.json()["items"][0]["sentiment"] == "negative"


@pytest.mark.asyncio
async def test_autoreply_config_default(client, channel_id):
    r = client.get(f"/api/v1/channels/{channel_id}/autoreply")
    assert r.status_code == 200
    body = r.json()
    assert body["enabled"] is False
    assert body["approval_mode"] == "auto"
    assert body["custom_instructions"] is None


@pytest.mark.asyncio
async def test_autoreply_config_update(client, channel_id):
    r = client.put(
        f"/api/v1/channels/{channel_id}/autoreply",
        json={"approval_mode": "approval", "custom_instructions": "Never mention refunds."},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["approval_mode"] == "approval"
    assert body["custom_instructions"] == "Never mention refunds."


@pytest.mark.asyncio
async def test_autoreply_config_invalid_approval_mode(client, channel_id):
    r = client.put(
        f"/api/v1/channels/{channel_id}/autoreply",
        json={"approval_mode": "maybe"},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_reply_generate_creates_pending(client, channel_id):
    r = client.post(
        f"/api/v1/channels/{channel_id}/reviews/generate",
        json={
            "review_id": "accounts/1/locations/1/reviews/abc",
            "rating": 2,
            "review_text": "Slow service, rude staff, dirty tables.",
            "reviewer_name": "Aisha K.",
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "pending_approval"
    assert len(body["reply_text"]) > 10


@pytest.mark.asyncio
async def test_reply_generate_duplicate(client, channel_id):
    payload = {
        "review_id": "accounts/1/locations/1/reviews/abc",
        "rating": 2,
        "review_text": "Slow service, rude staff, dirty tables.",
        "reviewer_name": "Aisha K.",
    }
    first = client.post(f"/api/v1/channels/{channel_id}/reviews/generate", json=payload)
    assert first.status_code == 201
    second = client.post(f"/api/v1/channels/{channel_id}/reviews/generate", json=payload)
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_reply_approve_then_reject(client, channel_id):
    payload = {
        "review_id": "accounts/1/locations/1/reviews/abc",
        "rating": 2,
        "review_text": "Slow service, rude staff, dirty tables.",
        "reviewer_name": "Aisha K.",
    }
    created = client.post(f"/api/v1/channels/{channel_id}/reviews/generate", json=payload)
    reply_id = created.json()["id"]

    # edit the draft
    edited = client.put(
        f"/api/v1/channels/{channel_id}/reviews/{reply_id}",
        json={"reply_text": "Thank you — we're sorry and we're fixing this."},
    )
    assert edited.status_code == 200
    assert edited.json()["reply_text"].startswith("Thank you")

    # approve (mock mode posts successfully)
    approved = client.post(f"/api/v1/channels/{channel_id}/reviews/{reply_id}/approve")
    assert approved.status_code == 200
    assert approved.json()["status"] == "posted"

    # cannot reject an already-published reply
    rejected = client.delete(f"/api/v1/channels/{channel_id}/reviews/{reply_id}")
    assert rejected.status_code == 400


@pytest.mark.asyncio
async def test_reply_reject_pending(client, channel_id):
    payload = {
        "review_id": "accounts/1/locations/1/reviews/xyz",
        "rating": 1,
        "review_text": "Very disappointed.",
        "reviewer_name": "Sara T.",
    }
    created = client.post(f"/api/v1/channels/{channel_id}/reviews/generate", json=payload)
    reply_id = created.json()["id"]
    rejected = client.delete(f"/api/v1/channels/{channel_id}/reviews/{reply_id}")
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"


@pytest.mark.asyncio
async def test_reply_regenerate(client, channel_id):
    payload = {
        "review_id": "accounts/1/locations/1/reviews/regen",
        "rating": 3,
        "review_text": "Food was okay but we waited 30 minutes.",
        "reviewer_name": "Daniel M.",
    }
    created = client.post(f"/api/v1/channels/{channel_id}/reviews/generate", json=payload)
    reply_id = created.json()["id"]
    first_text = created.json()["reply_text"]

    regenerated = client.post(f"/api/v1/channels/{channel_id}/reviews/{reply_id}/regenerate")
    assert regenerated.status_code == 200
    assert regenerated.json()["reply_text"] != first_text


@pytest.mark.asyncio
async def test_executive_summary(client):
    r = client.get("/api/v1/analytics/executive-summary?days=30")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body["headline"], str) and body["headline"]
    assert isinstance(body["recommended_action"], str)
    assert isinstance(body["benchmark_text"], str)
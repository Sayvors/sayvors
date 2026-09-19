"""API integration tests: analytics overview, reply workflow, config."""
import pytest

from app.modules.channels.models import ReviewReply


@pytest.mark.asyncio
async def test_review_intelligence_empty(client):
    r = client.get("/api/v1/analytics/review-intelligence?days=90", headers={"host": "localhost"})
    assert r.status_code == 200
    assert r.json() is None


@pytest.mark.asyncio
async def test_review_intelligence_analyze_and_serve(client, db, channel_id, user_id, monkeypatch):
    from app.modules.analytics import intelligence_ai as intelligence_ai_mod

    report = {
        "source": "fallback", "model": None,
        "stats": {"total": 1, "avg_rating": 4.0,
                  "distribution": {"5": 0, "4": 1, "3": 0, "2": 0, "1": 0},
                  "positive": 1, "neutral": 0, "negative": 0,
                  "replied": 0, "unanswered": 1, "response_rate": 0},
        "summary": "Canned summary.",
        "themes": [{"name": "quality", "mentions": 1, "avg_rating": 4.0,
                    "positive_pct": 100, "phrases": [], "trend": "stable"}],
        "opportunities": [], "strengths": [], "actions": [],
        "rag_used": False, "rag_chunks": 0, "rag_bank": None,
        "fallback_reason": "test",
        "analyzed_at": "2026-09-09T00:00:00+00:00",
        "review_count": 1, "current_count": 1, "stale": False,
    }

    async def _fake_analyze(db_, user_, channel_id=None, days=90, databank_id=None):
        return report

    async def _fake_stored(db_, user_id_, channel_id=None, days=90):
        return report

    monkeypatch.setattr(intelligence_ai_mod, "analyze_and_store", _fake_analyze)
    monkeypatch.setattr(intelligence_ai_mod, "get_stored_report", _fake_stored)

    r = client.post(
        "/api/v1/analytics/review-intelligence/analyze",
        json={"days": 90},
        headers={"host": "localhost"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["summary"] == "Canned summary."
    assert body["stats"]["total"] == 1
    assert body["themes"][0]["name"] == "quality"

    r = client.get("/api/v1/analytics/review-intelligence?days=90", headers={"host": "localhost"})
    assert r.status_code == 200
    assert r.json()["analyzed_at"] == "2026-09-09T00:00:00+00:00"


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


@pytest.mark.asyncio
async def test_autoreply_model_restricted_to_admin_enabled(client, channel_id):
    host = {"host": "localhost"}
    # Unknown model id rejected.
    r = client.put(
        f"/api/v1/channels/{channel_id}/autoreply",
        json={"model": "not-a-model"},
        headers=host,
    )
    assert r.status_code == 422
    # Known model without an admin key rejected.
    r = client.put(
        f"/api/v1/channels/{channel_id}/autoreply",
        json={"model": "openai:gpt-4o-mini"},
        headers=host,
    )
    assert r.status_code == 422
    assert "administrator" in r.json()["detail"]
    # Non-model fields still save fine.
    r = client.put(
        f"/api/v1/channels/{channel_id}/autoreply",
        json={"tone": "professional"},
        headers=host,
    )
    assert r.status_code == 200
    assert r.json()["tone"] == "professional"


@pytest.mark.asyncio
async def test_autoreply_model_accepts_admin_saved(client, channel_id, db):
    """A model the admin saved + keyed is assignable; the picker lists it."""
    from app.modules.channels.service import encrypt_token
    from app.modules.llm.models import ModelConfig, ProviderConfig

    db.add(ProviderConfig(
        provider="groq", key_encrypted=encrypt_token("gsk_test"), enabled=True,
    ))
    db.add(ModelConfig(model_id="groq:oss-120b", enabled=True))
    await db.commit()

    host = {"host": "localhost"}
    r = client.put(
        f"/api/v1/channels/{channel_id}/autoreply",
        json={"model": "groq:oss-120b"},
        headers=host,
    )
    assert r.status_code == 200, r.text[:200]
    assert r.json()["model"] == "groq:oss-120b"

    r = client.get("/api/v1/llm/models", headers=host)
    assert [m["id"] for m in r.json()["models"]] == ["groq:oss-120b"]


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
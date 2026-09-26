"""API integration tests: analytics overview, reply workflow, config."""
import pytest

from app.modules.channels.models import ReviewReply


@pytest.fixture(autouse=True)
def _canned_reply_generation(monkeypatch):
    """Hermetic reply-draft generation — no LLM key needed for the workflow.

    The real `generate_auto_reply` needs a live provider; these tests
    exercise the workflow around it (queues, approvals, edit follow-ups).
    """
    from app.modules.channels import review_reply as rr

    async def _fake(config, channel, rating, text, reviewer_name, db,
                    review_id=None, attempt=1, previous_draft=None):
        return f"canned reply ({rating}) try {attempt} to: {text}"

    monkeypatch.setattr(rr, "generate_auto_reply", _fake)


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
        "dimensions": [{"key": "quality", "label": "Product/Service Quality",
                        "standard": True, "mentions": 1, "positive": 1, "negative": 0,
                        "avg_rating": 4.0, "positive_pct": 100, "signal": "strong",
                        "confidence": "low", "verdict": "1 review(s) praise it.",
                        "evidence": [{"quote": "good", "rating": 4}]}],
        "competitive": {"wins": [], "gaps": [], "scope": None},
        "scope_key": "90",
        "rag_used": False, "rag_chunks": 0, "rag_bank": None,
        "fallback_reason": "test",
        "analyzed_at": "2026-09-09T00:00:00+00:00",
        "review_count": 1, "current_count": 1, "stale": False,
    }

    async def _fake_analyze(db_, user_, channel_id=None, days=90, databank_id=None,
                            date_from=None, date_to=None):
        return report

    async def _fake_stored(db_, user_id_, channel_id=None, days=90,
                           date_from=None, date_to=None):
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
async def test_autoreply_model_empty_resets_to_tenant_default(client, channel_id, db):
    """Empty string clears the explicit choice → null = tenant default."""
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
    assert r.status_code == 200
    assert r.json()["model"] == "groq:oss-120b"

    r = client.put(
        f"/api/v1/channels/{channel_id}/autoreply",
        json={"model": ""},
        headers=host,
    )
    assert r.status_code == 200, r.text[:200]
    assert r.json()["model"] is None


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
    # Idempotent: the existing draft is returned instead of a duplicate.
    assert second.status_code == 201
    assert second.json()["id"] == first.json()["id"]


@pytest.mark.asyncio
async def test_reply_generate_followup_for_edited_review(client, db, channel_id, user_id):
    """A review that was already answered can still get a fresh draft when
    the reviewer edited it — the on-demand path behind the dashboard's
    'Generate draft now' button."""
    from datetime import datetime, timezone

    from sqlalchemy import select

    from app.modules.analytics.models import ReviewInsight
    from app.modules.channels.models import ReviewReply

    review_id = "accounts/1/locations/1/reviews/edited-1"
    db.add(ReviewReply(
        channel_id=channel_id, review_id=review_id, rating=5,
        review_text="Great!", reviewer_name="Old Name",
        reply_text="old live reply", status="posted",
    ))
    db.add(ReviewInsight(
        id="ins-fu-1", user_id=user_id, channel_id=channel_id, review_id=review_id,
        rating=1, review_text="Actually broke", reviewer_name="Saeed",
        sentiment="negative", sentiment_score=-0.5, topics=[], products=[], problems=[],
        enrichment_status="done", replied=True, edited=True,
        edited_at=datetime.now(timezone.utc),
        previous_rating=5, previous_review_text="Great!",
    ))
    await db.commit()

    payload = {
        "review_id": review_id,
        "rating": 1,
        "review_text": "Actually broke",
        "reviewer_name": "Saeed",
    }
    r = client.post(f"/api/v1/channels/{channel_id}/reviews/generate", json=payload)
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "pending_approval"
    assert body["review_text"] == "Actually broke"

    # Un-edited reviews with a live reply stay blocked.
    db.add(ReviewReply(
        channel_id=channel_id, review_id="accounts/1/locations/1/reviews/plain",
        rating=5, review_text="Nice", reply_text="live", status="posted",
    ))
    await db.commit()
    blocked = client.post(f"/api/v1/channels/{channel_id}/reviews/generate", json={
        "review_id": "accounts/1/locations/1/reviews/plain",
        "rating": 5, "review_text": "Nice", "reviewer_name": "X",
    })
    assert blocked.status_code == 409
    rows = (await db.execute(select(ReviewReply))).scalars().all()
    assert len([r for r in rows if r.review_id == "accounts/1/locations/1/reviews/plain"]) == 1


@pytest.mark.asyncio
async def test_reply_approve_then_reject(client, channel_id, monkeypatch):
    # Publish through the Localith path with a patched poster — mock mode
    # refuses GBP publishing by design (no real listing in tests).
    from app.modules.channels import router as channels_router
    from app.modules.localith import service as localith_service

    monkeypatch.setattr(channels_router.settings, "GOOGLE_REVIEWS_MOCK", False)
    posted: list[tuple[str, str]] = []

    async def _post(item_id, text):
        posted.append((item_id, text))
        return {"ok": True}

    monkeypatch.setattr(localith_service, "post_reply", _post)

    payload = {
        "review_id": "localith:abc123",
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

    # approve (Localith publish path, patched poster)
    approved = client.post(f"/api/v1/channels/{channel_id}/reviews/{reply_id}/approve")
    assert approved.status_code == 200
    assert approved.json()["status"] == "posted"
    assert posted == [("abc123", "Thank you — we're sorry and we're fixing this.")]

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


@pytest.mark.asyncio
async def test_insights_expose_edit_flag_and_dismiss(client, db, channel_id, user_id):
    from datetime import datetime, timezone

    from app.modules.analytics.models import ReviewInsight

    db.add(ReviewInsight(
        id="ins-edit-9", user_id=user_id, channel_id=channel_id, review_id="r-edit",
        rating=2, review_text="Updated: got worse", reviewer_name="A",
        sentiment="negative", sentiment_score=-0.5, topics=[], products=[], problems=[],
        enrichment_status="done", replied=False,
        edited=True, edited_at=datetime.now(timezone.utc),
        previous_rating=5, previous_review_text="Great!",
    ))
    await db.commit()

    # The flag + snapshot are visible in the insights list payload.
    items = client.get("/api/v1/analytics/reviews/insights").json()["items"]
    flagged = [i for i in items if i["id"] == "ins-edit-9"]
    assert flagged and flagged[0]["edited"] is True
    assert flagged[0]["previous_rating"] == 5
    assert flagged[0]["previous_review_text"] == "Great!"

    r = client.post("/api/v1/analytics/reviews/insights/ins-edit-9/dismiss-edit")
    assert r.status_code == 200
    body = r.json()
    assert body["edited"] is False
    assert body["edited_at"] is None
    assert body["previous_rating"] is None
    assert body["previous_review_text"] is None

    # Unknown id -> 404.
    assert client.post(
        "/api/v1/analytics/reviews/insights/does-not-exist/dismiss-edit"
    ).status_code == 404

    # The edited=true filter finds it again after a fresh edit.
    db.add(ReviewInsight(
        id="ins-edit-10", user_id=user_id, channel_id=channel_id, review_id="r-edit-2",
        rating=1, review_text="Rewritten", reviewer_name="B",
        sentiment="negative", sentiment_score=-0.5, topics=[], products=[], problems=[],
        enrichment_status="done", replied=False,
        edited=True, previous_rating=4, previous_review_text="Old text",
    ))
    await db.commit()
    body = client.get("/api/v1/analytics/reviews/insights?edited=true").json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == "ins-edit-10"
    # Unedited reviews stay outside the filter.
    body = client.get("/api/v1/analytics/reviews/insights?edited=false").json()
    assert all(i["id"] != "ins-edit-10" for i in body["items"])
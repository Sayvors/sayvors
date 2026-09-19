"""Reply generation model fallback (no network)."""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.modules.channels import review_reply
from app.modules.llm.providers.base import LLMResponse, LLMUsage, ProviderError


def _resp(text):
    return LLMResponse(
        content=text, provider="groq", model="openai/gpt-oss-120b",
        usage=LLMUsage(prompt_tokens=10, completion_tokens=20, total_tokens=30),
        finish_reason="stop",
    )


class _FakeDB:
    """The generator closes the session before the LLM call."""

    async def close(self):
        return None


class _DeadProvider:
    async def complete(self, req):
        raise ProviderError("openai", "API key not configured", 503)


class _GroqProvider:
    def __init__(self):
        self.models_seen = []

    async def complete(self, req):
        self.models_seen.append(req.model)
        return _resp("Thank you for the great review!")


@pytest.mark.asyncio
async def test_falls_back_to_groq_when_configured_model_dead(monkeypatch):
    monkeypatch.setattr("app.config.settings.GOOGLE_REVIEWS_MOCK", False)
    groq = _GroqProvider()

    def _fake_get(model_id):
        if model_id == "groq:openai/gpt-oss-120b":
            return groq
        return _DeadProvider()

    monkeypatch.setattr(review_reply, "get_provider_for_model", _fake_get)
    config = SimpleNamespace(model="openai:gpt-4o-mini", tone="friendly",
                             databank_id=None, custom_instructions=None)
    text = await review_reply.generate_review_reply(
        config, 5, "Loved it", "Sara", _FakeDB()
    )
    assert text == "Thank you for the great review!"
    assert groq.models_seen == ["openai/gpt-oss-120b"]


@pytest.mark.asyncio
async def test_no_retry_when_groq_itself_fails(monkeypatch):
    monkeypatch.setattr("app.config.settings.GOOGLE_REVIEWS_MOCK", False)
    calls = []

    def _fake_get(model_id):
        calls.append(model_id)

        class _Fail:
            async def complete(self, req):
                raise ProviderError("groq", "boom", 502)

        return _Fail()

    monkeypatch.setattr(review_reply, "get_provider_for_model", _fake_get)
    config = SimpleNamespace(model="groq:openai/gpt-oss-120b", tone="friendly",
                             databank_id=None, custom_instructions=None)
    with pytest.raises(ProviderError):
        await review_reply.generate_review_reply(config, 5, "Loved it", "Sara", _FakeDB())
    assert calls == ["groq:openai/gpt-oss-120b"]


@pytest.mark.asyncio
async def test_rejected_status_round_trips(db, user_id, channel_id):
    """Regression: 'rejected' must be a loadable enum value (500 on discard)."""
    from app.modules.channels.models import ReviewReply

    db.add(ReviewReply(
        id="rr-rej-1", channel_id=channel_id, review_id="localith:x",
        rating=4, review_text="t", reviewer_name="n",
        reply_text="draft", status="rejected",
    ))
    await db.commit()
    db.expunge_all()
    row = await db.get(ReviewReply, "rr-rej-1")
    assert row is not None
    assert row.status == "rejected"


# ── reply language: Arabic review → Arabic reply ──────────

@pytest.mark.asyncio
async def test_arabic_review_gets_arabic_language_instruction(monkeypatch):
    monkeypatch.setattr("app.config.settings.GOOGLE_REVIEWS_MOCK", False)
    captured = {}

    class _Capture:
        async def complete(self, req):
            captured["system"] = req.system_prompt
            return _resp("شكراً جزيلاً على تقييمك!")

    monkeypatch.setattr(review_reply, "get_provider_for_model", lambda model: _Capture())
    config = SimpleNamespace(model="groq:openai/gpt-oss-120b", tone="friendly",
                             databank_id=None, custom_instructions=None)
    text = await review_reply.generate_review_reply(
        config, 5, "الطعام رائع والخدمة ممتازة", "أحمد", _FakeDB()
    )
    assert text == "شكراً جزيلاً على تقييمك!"
    assert "in Arabic" in captured["system"]
    assert "العربية" in captured["system"]


@pytest.mark.asyncio
async def test_english_review_gets_language_match_rule(monkeypatch):
    monkeypatch.setattr("app.config.settings.GOOGLE_REVIEWS_MOCK", False)
    captured = {}

    class _Capture:
        async def complete(self, req):
            captured["system"] = req.system_prompt
            return _resp("Thanks for the kind words!")

    monkeypatch.setattr(review_reply, "get_provider_for_model", lambda model: _Capture())
    config = SimpleNamespace(model="groq:openai/gpt-oss-120b", tone="friendly",
                             databank_id=None, custom_instructions=None)
    await review_reply.generate_review_reply(config, 5, "Loved it", "Sara", _FakeDB())
    assert "SAME language as the review" in captured["system"]


@pytest.mark.asyncio
async def test_mock_mode_arabic_review_returns_arabic_reply(monkeypatch):
    monkeypatch.setattr("app.config.settings.GOOGLE_REVIEWS_MOCK", True)
    config = SimpleNamespace(model="groq:openai/gpt-oss-120b", tone="friendly",
                             databank_id=None, custom_instructions=None)
    text = await review_reply.generate_review_reply(
        config, 5, "مطعم رائع جداً", "أحمد", _FakeDB()
    )
    # Arabic script present, no English canned text
    assert any("؀" <= ch <= "ۿ" for ch in text)
    assert "Thank you" not in text


# ── question-type reviews: inquiries, not feedback ─────────

@pytest.mark.asyncio
async def test_question_review_prompt_never_thanks(monkeypatch):
    """"هل تبيعون شاورما؟" is an inquiry — the prompt must not instruct the
    model to thank the reviewer for a "wonderful review"."""
    monkeypatch.setattr("app.config.settings.GOOGLE_REVIEWS_MOCK", False)
    captured = {}

    class _Capture:
        async def complete(self, req):
            captured["system"] = req.system_prompt
            return _resp("سؤالك في محل!")

    monkeypatch.setattr(review_reply, "get_provider_for_model", lambda model: _Capture())
    config = SimpleNamespace(model="groq:openai/gpt-oss-120b", tone="friendly",
                             databank_id=None, custom_instructions=None)
    await review_reply.generate_review_reply(
        config, 5, "هل تبيعون شاورما؟", "سعيد", _FakeDB()
    )
    assert "QUESTION" in captured["system"]
    assert "do NOT thank them" in captured["system"]
    assert "thank the reviewer warmly" not in captured["system"]


@pytest.mark.asyncio
async def test_prompt_bans_invented_business_facts(monkeypatch):
    """No databank context = no facts — the model may not invent a menu."""
    monkeypatch.setattr("app.config.settings.GOOGLE_REVIEWS_MOCK", False)
    captured = {}

    class _Capture:
        async def complete(self, req):
            captured["system"] = req.system_prompt
            return _resp("ok")

    monkeypatch.setattr(review_reply, "get_provider_for_model", lambda model: _Capture())
    config = SimpleNamespace(model="groq:openai/gpt-oss-120b", tone="friendly",
                             databank_id=None, custom_instructions=None)
    await review_reply.generate_review_reply(config, 5, "Loved it", "Sara", _FakeDB())
    assert "NEVER invent products" in captured["system"]
    assert "follow up with accurate details" in captured["system"]


@pytest.mark.asyncio
async def test_mock_mode_question_gets_answer_not_thanks(monkeypatch):
    monkeypatch.setattr("app.config.settings.GOOGLE_REVIEWS_MOCK", True)
    config = SimpleNamespace(model="groq:openai/gpt-oss-120b", tone="friendly",
                             databank_id=None, custom_instructions=None)
    ar = await review_reply.generate_review_reply(
        config, 5, "هل تبيعون شاورما؟", "سعيد", _FakeDB()
    )
    assert "سؤالك" in ar
    en = await review_reply.generate_review_reply(
        config, 5, "Do you sell shawarma?", "Saeed", _FakeDB()
    )
    assert "question" in en.lower()


# ── outbox retry endpoint ─────────────────────────────────

@pytest.mark.asyncio
async def test_retry_failed_reply_returns_to_queue(db, user_id, channel_id, client):
    """Retry: a failed publish row goes back to pending_approval, error cleared."""
    from app.modules.channels.models import ReviewReply

    db.add(ReviewReply(
        id="rr-retry-1", channel_id=channel_id, review_id="localith:xyz",
        rating=5, review_text="Great", reviewer_name="Ali",
        reply_text="Thanks, Ali!", status="failed", error="No refresh token available",
    ))
    await db.commit()

    r = client.post(
        f"/api/v1/channels/{channel_id}/reviews/rr-retry-1/retry",
        headers={"host": "localhost"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "pending_approval"
    assert body["error"] is None


@pytest.mark.asyncio
async def test_retry_failed_reply_regenerates_empty_text(db, user_id, channel_id, client):
    """Retry with empty text (generation failure) regenerates the draft."""
    from app.modules.channels.models import ReviewReply

    db.add(ReviewReply(
        id="rr-retry-2", channel_id=channel_id, review_id="localith:xyz2",
        rating=4, review_text="Nice place", reviewer_name="Omar",
        reply_text="", status="failed", error="LLM down",
    ))
    await db.commit()

    r = client.post(
        f"/api/v1/channels/{channel_id}/reviews/rr-retry-2/retry",
        headers={"host": "localhost"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "pending_approval"
    assert len(body["reply_text"]) > 5
    assert body["error"] is None


@pytest.mark.asyncio
async def test_retry_rejects_non_failed(db, user_id, channel_id, client):
    """Retry only applies to failed rows."""
    from app.modules.channels.models import ReviewReply

    db.add(ReviewReply(
        id="rr-retry-3", channel_id=channel_id, review_id="localith:xyz3",
        rating=5, review_text="Great", reviewer_name="Ali",
        reply_text="Thanks!", status="posted",
    ))
    await db.commit()

    r = client.post(
        f"/api/v1/channels/{channel_id}/reviews/rr-retry-3/retry",
        headers={"host": "localhost"},
    )
    assert r.status_code == 400


# ── edit any response ───────────────────────────────────────

def _reply(row_id, channel_id, status, **over):
    from app.modules.channels.models import ReviewReply

    base = dict(
        id=row_id, channel_id=channel_id, review_id="localith:edit-1",
        rating=5, review_text="Great", reviewer_name="Ali",
        reply_text="Thanks!", status=status,
    )
    base.update(over)
    return ReviewReply(**base)


@pytest.mark.asyncio
async def test_edit_posted_sends_back_for_approval(db, user_id, channel_id, client):
    """Editing a posted reply updates the text and re-queues it — the
    update only goes live after a fresh approval."""
    db.add(_reply("rr-edit-1", channel_id, "posted", generation_attempt=1))
    await db.commit()

    r = client.put(
        f"/api/v1/channels/{channel_id}/reviews/rr-edit-1",
        json={"reply_text": "Thanks, updated!"},
        headers={"host": "localhost"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["reply_text"] == "Thanks, updated!"
    assert body["status"] == "pending_approval"
    assert body["generation_attempt"] == 2


@pytest.mark.asyncio
async def test_edit_failed_requeues(db, user_id, channel_id, client):
    db.add(_reply("rr-edit-2", channel_id, "failed", error="boom"))
    await db.commit()

    r = client.put(
        f"/api/v1/channels/{channel_id}/reviews/rr-edit-2",
        json={"reply_text": "Retry text"},
        headers={"host": "localhost"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "pending_approval"
    assert body["error"] is None


@pytest.mark.asyncio
async def test_edit_rejected_still_refused(db, user_id, channel_id, client):
    db.add(_reply("rr-edit-3", channel_id, "rejected"))
    await db.commit()

    r = client.put(
        f"/api/v1/channels/{channel_id}/reviews/rr-edit-3",
        json={"reply_text": "Nope"},
        headers={"host": "localhost"},
    )
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_insights_carry_latest_response(db, user_id, channel_id, client):
    """The review list carries each review's response for inline editing."""
    from datetime import datetime, timezone

    from app.modules.analytics.models import ReviewInsight

    db.add(ReviewInsight(
        id="ins-resp-1", user_id=user_id, channel_id=channel_id,
        review_id="localith:edit-1", rating=5, review_text="Great",
        reviewer_name="Ali", sentiment="positive", sentiment_score=0.9,
        topics=[], products=[], problems=[], enrichment_status="done",
        replied=True, review_updated_at=datetime.now(timezone.utc),
    ))
    db.add(_reply("rr-edit-4", channel_id, "posted", reply_text="Live text"))
    await db.commit()

    r = client.get("/api/v1/analytics/reviews/insights", headers={"host": "localhost"})
    assert r.status_code == 200
    item = [i for i in r.json()["items"] if i["id"] == "ins-resp-1"][0]
    assert item["reply_id"] == "rr-edit-4"
    assert item["reply_text"] == "Live text"
    assert item["reply_status"] == "posted"




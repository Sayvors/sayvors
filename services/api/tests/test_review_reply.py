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
        config, 5, "Loved it", "Sara", object()
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
        await review_reply.generate_review_reply(config, 5, "Loved it", "Sara", object())
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
        config, 5, "الطعام رائع والخدمة ممتازة", "أحمد", object()
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
    await review_reply.generate_review_reply(config, 5, "Loved it", "Sara", object())
    assert "SAME language as the review" in captured["system"]


@pytest.mark.asyncio
async def test_mock_mode_arabic_review_returns_arabic_reply(monkeypatch):
    monkeypatch.setattr("app.config.settings.GOOGLE_REVIEWS_MOCK", True)
    config = SimpleNamespace(model="groq:openai/gpt-oss-120b", tone="friendly",
                             databank_id=None, custom_instructions=None)
    text = await review_reply.generate_review_reply(
        config, 5, "مطعم رائع جداً", "أحمد", object()
    )
    # Arabic script present, no English canned text
    assert any("؀" <= ch <= "ۿ" for ch in text)
    assert "Thank you" not in text


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

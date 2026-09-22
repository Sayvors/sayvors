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


def _shim_session_factory(session):
    """Redirect the engine's private log-write session to the test DB."""

    class _Factory:
        def __call__(self):
            return self

        async def __aenter__(self):
            return session

        async def __aexit__(self, *args):
            return False

    return _Factory()


def _analysis_json(**over):
    import json as _json

    base = {"sentiment": "positive", "emotion": "joy", "intent": ["praise"],
            "issue_type": None, "product_reference": None, "urgency": "low",
            "customer_request": None, "language": "en"}
    base.update(over)
    return _json.dumps(base)


class _AnalysisProvider:
    def __init__(self, analysis_text):
        self.analysis_text = analysis_text
        self.calls = []

    async def complete(self, req):
        self.calls.append(req.model)
        return _resp(self.analysis_text)


class _ReplyProvider:
    def __init__(self, text):
        self.text = text
        self.captured = {}

    async def complete(self, req):
        self.captured["prompt"] = "\n".join(
            m.content for m in req.messages)
        self.captured["system"] = req.system_prompt
        return _resp(self.text)


async def _enable_test_model(db, model_id="groq:oss-120b",
                             provider="groq"):
    """Admin-enabled model rows so explicit choices validate."""
    from app.modules.channels.service import encrypt_token
    from app.modules.llm.models import ModelConfig, ProviderConfig

    db.add(ProviderConfig(
        provider=provider, key_encrypted=encrypt_token("gsk_test"),
        enabled=True,
    ))
    db.add(ModelConfig(model_id=model_id, enabled=True))
    await db.commit()


@pytest.mark.asyncio
async def test_dead_model_fails_loudly_without_fallback(monkeypatch, db, user_id):
    """No model fallbacks: a dead configured model raises (single attempt)
    so the admin fixes the key instead of silently switching providers."""
    import app.modules.review_engine.service as eng
    import app.modules.review_engine.understanding as und

    monkeypatch.setattr("app.config.settings.GOOGLE_REVIEWS_MOCK", False)
    monkeypatch.setattr(eng, "_async_session", _shim_session_factory(db))
    await _enable_test_model(db, "openai:gpt-4o-mini", provider="openai")
    calls = []

    class _DeadCountingProvider:
        async def complete(self, req):
            calls.append(req.model)
            raise ProviderError("openai", "API key not configured", 503)

    monkeypatch.setattr(
        und, "get_provider_for_model", lambda mid: _DeadCountingProvider()
    )
    monkeypatch.setattr(und, "_resolve_model", lambda mid: ("api-x", "openai"))
    from app.modules.review_engine.schemas import ReviewEngineRequest

    req = ReviewEngineRequest(review_text="Loved it", rating=5,
                              reviewer_name="Sara",
                              model="openai:gpt-4o-mini")
    with pytest.raises(ProviderError):
        await eng.process_review(req, user_id, db)
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_no_retry_when_groq_itself_fails(monkeypatch, db, user_id):
    import app.modules.review_engine.service as eng
    import app.modules.review_engine.understanding as und

    monkeypatch.setattr("app.config.settings.GOOGLE_REVIEWS_MOCK", False)
    monkeypatch.setattr(eng, "_async_session", _shim_session_factory(db))
    await _enable_test_model(db, "groq:oss-120b", provider="groq")
    calls = []

    def _fake_get(model_id):
        calls.append(model_id)

        class _Fail:
            async def complete(self, req):
                raise ProviderError("groq", "boom", 502)

        return _Fail()

    monkeypatch.setattr(und, "get_provider_for_model", _fake_get)
    monkeypatch.setattr(und, "_resolve_model", lambda mid: ("api-x", "groq"))
    from app.modules.review_engine.schemas import ReviewEngineRequest

    req = ReviewEngineRequest(review_text="Loved it", rating=5,
                              reviewer_name="Sara",
                              model="groq:oss-120b")
    with pytest.raises(ProviderError):
        await eng.process_review(req, user_id, db)
    assert calls == ["groq:oss-120b"]


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


# ── reply language: Arabic review → Arabic reply (engine level) ──

@pytest.mark.asyncio
async def test_arabic_review_gets_arabic_language_instruction(monkeypatch, db, user_id):
    import app.modules.review_engine.generator as gen
    import app.modules.review_engine.service as eng
    import app.modules.review_engine.understanding as und

    monkeypatch.setattr("app.config.settings.GOOGLE_REVIEWS_MOCK", False)
    monkeypatch.setattr(eng, "_async_session", _shim_session_factory(db))
    await _enable_test_model(db, "groq:oss-120b", provider="groq")
    monkeypatch.setattr(
        und, "get_provider_for_model",
        lambda mid: _AnalysisProvider(_analysis_json(language="ar")),
    )
    monkeypatch.setattr(und, "_resolve_model", lambda mid: ("api-x", "groq"))
    reply = _ReplyProvider("شكراً جزيلاً على تقييمك!")
    monkeypatch.setattr(gen, "get_provider_for_model", lambda mid: reply)
    monkeypatch.setattr(gen, "_resolve_model", lambda mid: ("api-x", "groq"))

    from app.modules.review_engine.schemas import ReviewEngineRequest

    req = ReviewEngineRequest(
        review_text="الطعام رائع والخدمة ممتازة", rating=5,
        reviewer_name="أحمد", model="groq:oss-120b")
    resp = await eng.process_review(req, user_id, db)
    assert resp.response_text == "شكراً جزيلاً على تقييمك!"
    assert "in Arabic" in reply.captured["prompt"]
    assert "Write your ENTIRE reply in Arabic" in reply.captured["prompt"]


@pytest.mark.asyncio
async def test_english_review_gets_language_match_rule(monkeypatch, db, user_id):
    import app.modules.review_engine.generator as gen
    import app.modules.review_engine.service as eng
    import app.modules.review_engine.understanding as und

    monkeypatch.setattr("app.config.settings.GOOGLE_REVIEWS_MOCK", False)
    monkeypatch.setattr(eng, "_async_session", _shim_session_factory(db))
    await _enable_test_model(db, "groq:oss-120b", provider="groq")
    monkeypatch.setattr(
        und, "get_provider_for_model",
        lambda mid: _AnalysisProvider(_analysis_json()),
    )
    monkeypatch.setattr(und, "_resolve_model", lambda mid: ("api-x", "groq"))
    reply = _ReplyProvider("Thanks for the kind words!")
    monkeypatch.setattr(gen, "get_provider_for_model", lambda mid: reply)
    monkeypatch.setattr(gen, "_resolve_model", lambda mid: ("api-x", "groq"))

    from app.modules.review_engine.schemas import ReviewEngineRequest

    req = ReviewEngineRequest(review_text="Loved it", rating=5,
                              reviewer_name="Sara",
                              model="groq:oss-120b")
    resp = await eng.process_review(req, user_id, db)
    assert resp.response_text == "Thanks for the kind words!"
    # English review: the engine must not steer toward any other language.
    assert "العربية" not in reply.captured["prompt"]
    assert "in Arabic" not in reply.captured["prompt"]


@pytest.mark.asyncio
async def test_mock_mode_arabic_review_returns_arabic_reply(monkeypatch):
    monkeypatch.setattr("app.config.settings.GOOGLE_REVIEWS_MOCK", True)
    config = SimpleNamespace(model="groq:oss-120b", tone="friendly")
    channel = SimpleNamespace(id=None, user_id=None)
    text = await review_reply.generate_auto_reply(
        config, channel, 5, "مطعم رائع جداً", "أحمد", None
    )
    # Arabic script present, no English canned text
    assert any("؀" <= ch <= "ۿ" for ch in text)
    assert "Thank you" not in text


# ── question-type reviews: inquiries, not feedback (engine requirements) ──

def _question_analysis():
    from app.modules.review_engine.schemas import ReviewAnalysis

    return ReviewAnalysis(sentiment="neutral", emotion="curiosity",
                          intent=["question"], issue_type=None,
                          product_reference=None, urgency="low",
                          customer_request="هل تبيعون شاورما؟", language="ar")


def test_question_review_requirements_never_thank():
    """"هل تبيعون شاورما؟" is an inquiry — requirements must not instruct
    the model to thank the reviewer for a "wonderful review"."""
    from app.modules.review_engine.service import build_requirements

    reqs = build_requirements(_question_analysis(), [], [], [], None,
                              "Business identity: test restaurant")
    blob = "\n".join(reqs)
    assert "QUESTION" in blob
    assert "Do NOT thank" in blob
    assert "thank the reviewer warmly" not in blob


def test_question_without_context_bans_invention():
    """No verified facts — the requirements forbid inventing a menu."""
    from app.modules.review_engine.service import build_requirements

    reqs = build_requirements(_question_analysis(), [], [], [], None, None)
    blob = "\n".join(reqs)
    assert "do NOT invent products" in blob
    assert "follow up with accurate details" in blob


@pytest.mark.asyncio
async def test_mock_mode_question_gets_answer_not_thanks(monkeypatch):
    monkeypatch.setattr("app.config.settings.GOOGLE_REVIEWS_MOCK", True)
    config = SimpleNamespace(model="groq:oss-120b", tone="friendly")
    channel = SimpleNamespace(id=None, user_id=None)
    ar = await review_reply.generate_auto_reply(
        config, channel, 5, "هل تبيعون شاورما؟", "سعيد", None
    )
    assert "سؤالك" in ar
    en = await review_reply.generate_auto_reply(
        config, channel, 5, "Do you sell shawarma?", "Saeed", None
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
async def test_reject_marks_draft_dismissed(db, user_id, channel_id, client):
    """Rejecting a draft marks the insight so auto-pipelines stop drafting."""
    from app.modules.analytics.models import ReviewInsight

    db.add(ReviewInsight(
        channel_id=channel_id, review_id="localith:edit-1", user_id=user_id,
        rating=5, review_text="Great", reviewer_name="Ali",
    ))
    db.add(_reply("rr-reject-1", channel_id, "pending_approval"))
    await db.commit()

    r = client.delete(
        f"/api/v1/channels/{channel_id}/reviews/rr-reject-1",
        headers={"host": "localhost"},
    )
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"

    from sqlalchemy import select as _select

    db.expunge_all()  # endpoint committed via its own session
    insight = (await db.execute(
        _select(ReviewInsight).where(
            ReviewInsight.channel_id == channel_id,
            ReviewInsight.review_id == "localith:edit-1",
        )
    )).scalar_one()
    assert insight.draft_dismissed is True


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





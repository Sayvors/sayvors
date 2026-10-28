"""Multilingual regression tests: Arabic, English, Urdu, Roman Urdu, mixed.

Covers language identification, question detection, relevance (including the
Arabic pizza-at-AI-company case), generation language, and the full pipeline.
"""
import json
from types import SimpleNamespace

import pytest
import pytest_asyncio

from app.core.language import detect_language
from app.modules.review_engine.schemas import ReviewAnalysis, ReviewEngineRequest
from app.modules.review_engine.understanding import _rule_based_analysis, looks_like_question
from app.modules.review_engine.relevance import assess_relevance


# ---------------------------------------------------------------------------
# 1. Language detection
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("هل يفتح المحل بعد الظهر؟", "ar"),
    ("ما هي خدماتكم", "ar"),
    ("کیا آپ کے پاس پیزا ہے؟", "ur"),
    ("پیزا بہت مہنگا ہے", "ur"),
    ("کیا آپ کی سروس اچھی ہے", "ur"),
    ("Does the shop open in the afternoon?", "en"),
    ("Great service, thank you", "en"),
    ("kya shop khula hai afternoon mein", "ur-Latn"),
    ("kya aap ke paas pizza hai", "ur-Latn"),
])
def test_detect_language(text, expected):
    v = detect_language(text)
    assert v.code == expected, (text, v.code, v.confidence)


def test_detect_language_not_script_only():
    v = detect_language("ما هي خدماتكم")
    assert v.code == "ar"
    v2 = detect_language("کیا آپ کی خدمت اچھی ہے")
    assert v2.code == "ur"


# ---------------------------------------------------------------------------
# 2. Question detection
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text, expected", [
    ("هل يفتح المحل بعد الظهر؟", True),
    ("کیا آپ کے پاس پیزا ہے؟", True),
    ("Does the shop open in the afternoon?", True),
    ("kya shop khula hai", True),
    ("ما هي خدماتكم", True),
    ("Great service, thank you", False),
    ("پیزا بہت مہنگا ہے", False),
])
def test_looks_like_question(text, expected):
    assert looks_like_question(text) is expected


# ---------------------------------------------------------------------------
# 3. Rule-based analysis language
# ---------------------------------------------------------------------------

def test_rule_based_language_arabic():
    a = _rule_based_analysis("هل يفتح المحل بعد الظهر؟", 5)
    assert a.language == "ar"


def test_rule_based_language_urdu():
    a = _rule_based_analysis("کیا آپ کے پاس پیزا ہے؟", 5)
    assert a.language == "ur"


def test_rule_based_language_english():
    a = _rule_based_analysis("Does the shop open in the afternoon?", 4)
    assert a.language == "en"


def test_rule_based_language_roman_urdu():
    a = _rule_based_analysis("kya shop khula hai afternoon mein", 4)
    assert a.language == "ur-Latn"


# ---------------------------------------------------------------------------
# 4. Relevance
# ---------------------------------------------------------------------------

AI_DOMAIN = {"terms": ["ai", "saas", "software", "sayvors", "company", "makkah", "branch", "data"]}


def test_arabic_pizza_at_ai_company_is_off_topic():
    analysis = ReviewAnalysis(
        sentiment="positive", emotion="joy", intent=["praise", "question"],
        issue_type=None, product_reference="بيتزا", urgency="low",
        customer_request="هل يفتح المحل بعد الظهر؟", language="ar",
    )
    v = assess_relevance("كانت الخدمة جيدة، والبيتزا رائعة حقًا. هل يفتح المحل بعد الظهر؟",
                         analysis, AI_DOMAIN)
    assert v["verdict"] == "off_topic"


def test_urdu_pizza_at_ai_company_is_off_topic():
    analysis = ReviewAnalysis(
        sentiment="positive", emotion="joy", intent=["praise", "question"],
        issue_type=None, product_reference="پیزا", urgency="low",
        customer_request="کیا آپ کے پاس پیزا ہے؟", language="ur",
    )
    v = assess_relevance("کیا آپ کے پاس پیزا ہے؟", analysis, AI_DOMAIN)
    assert v["verdict"] == "off_topic"


def test_english_pizza_at_ai_company_is_off_topic():
    analysis = ReviewAnalysis(
        sentiment="negative", emotion="disappointment", intent=["complaint"],
        issue_type="product_quality", product_reference="pizza", urgency="low",
        customer_request=None, language="en",
    )
    v = assess_relevance("the pizza was bad", analysis, AI_DOMAIN)
    assert v["verdict"] == "off_topic"


def test_no_product_mention_is_uncertain():
    analysis = ReviewAnalysis(
        sentiment="negative", emotion="disappointment", intent=["complaint"],
        issue_type=None, product_reference=None, urgency="low",
        customer_request=None, language="en",
    )
    v = assess_relevance("terrible service", analysis, AI_DOMAIN)
    assert v["verdict"] == "uncertain"


# ---------------------------------------------------------------------------
# 5. End-to-end pipeline (mocked LLM)
# ---------------------------------------------------------------------------

    from types import SimpleNamespace

    async def fake_complete(model, messages, system_prompt, temperature=0.1,
                           max_tokens=300, tenant_id=None, purpose=None,
                           channel_id=None, **kw):
        sp = system_prompt or ""
        if "Analyze the review" in sp:
            return SimpleNamespace(content=json.dumps(analysis_payload),
                                  usage=SimpleNamespace(total_tokens=10))
        if "relevance judge" in sp.lower() or "relevance judge" in sp:
            return SimpleNamespace(
                content=json.dumps({"verdict": judge_verdict, "reason": "pizza not in domain"}),
                usage=SimpleNamespace(total_tokens=5))
        return SimpleNamespace(content=json.dumps({"response_text": gen_text}),
                              usage=SimpleNamespace(total_tokens=20))

    return fake_complete


def _make_fake_complete(analysis_payload, gen_text, judge_verdict="off_topic"):
    from types import SimpleNamespace

    async def fake_complete(model, messages, system_prompt, temperature=0.1,
                           max_tokens=300, tenant_id=None, purpose=None,
                           channel_id=None, **kw):
        sp = system_prompt or ""
        if "Analyze the review" in sp:
            return SimpleNamespace(content=__import__("json").dumps(analysis_payload),
                                  usage=SimpleNamespace(total_tokens=10), finish_reason="stop")
        if "relevance judge" in sp.lower() or "relevance judge" in sp:
            return SimpleNamespace(
                content=__import__("json").dumps({"verdict": judge_verdict, "reason": "pizza not in domain"}),
                usage=SimpleNamespace(total_tokens=5), finish_reason="stop")
        return SimpleNamespace(content=__import__("json").dumps({"response_text": gen_text}),
                              usage=SimpleNamespace(total_tokens=20), finish_reason="stop")

    return fake_complete


def _install_fake(monkeypatch, fake):
    import app.modules.llm.gateway as gw
    import app.modules.review_engine.service as svc
    import app.modules.review_engine.understanding as und
    import app.modules.review_engine.generator as gen
    monkeypatch.setattr(gw, "complete", fake)
    monkeypatch.setattr(und, "complete", fake)
    monkeypatch.setattr(gen, "complete", fake)

    async def _resolve_engine_model(req, tenant_id, db):
        return ("openai:gpt-4o-mini", "test")

    async def _resolve_reply_prefs(req, tenant_id, db):
        return {"dialect": "auto", "reply_language": "match",
                "promo_product_mentions": False, "promo_links": False,
                "promo_only_relevant": False, "promo_max_ctas": None}

    async def _get_business_context(tid, db):
        return {"business_type": "AI / SaaS / Software", "business_name": "Sayvors"}

    async def _resolve_business_domain(channel_id, tenant_id, db):
        return {"terms": ["ai", "saas", "software", "sayvors", "company", "makkah", "branch", "data"],
                "sources": {}, "not_offered": []}

    class _FakeSession:
        def add(self, x):
            pass

        async def commit(self):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    def _fake_session_factory():
        return _FakeSession()

    monkeypatch.setattr(svc, "_resolve_engine_model", _resolve_engine_model)
    monkeypatch.setattr(svc, "_resolve_reply_prefs", _resolve_reply_prefs)
    monkeypatch.setattr("app.modules.profile.service.get_business_context", _get_business_context)
    monkeypatch.setattr(svc, "resolve_business_domain", _resolve_business_domain)
    monkeypatch.setattr(svc, "_async_session", _fake_session_factory)
    # (no _async_session override: log write goes to the real dev DB)


async def _resolve(db, preferred=None):
    return preferred or "openai:gpt-4o-mini"


@pytest.mark.asyncio
async def test_pipeline_urdu_pizza_is_needs_review(db, user_id, monkeypatch):
    import app.modules.review_engine.service as svc
    import app.modules.llm.gateway as gw

    analysis_payload = {
        "sentiment": "positive", "emotion": "joy",
        "intent": ["praise", "question"], "issue_type": None,
        "product_reference": "پیزا", "product_reference_en": "pizza",
        "urgency": "low", "customer_request": "کیا آپ کے پاس پیزا ہے؟",
        "language": "ur",
    }
    gen_text = "ہم آپ کی مدد کے لیے حاضر ہیں۔"
    fake = _make_fake_complete(analysis_payload, gen_text)
    _install_fake(monkeypatch, fake)

    from app.modules.review_engine.schemas import ReviewEngineRequest
    req = ReviewEngineRequest(
        review_text="کیا آپ کے پاس پیزا ہے؟", rating=5,
        reviewer_name="Ali", model="openai:gpt-4o-mini", channel="google_review",
    )
    resp = await svc.process_review(req, "t1", db)

    assert resp.analysis.language == "ur", resp.analysis.language
    assert resp.relevance is not None
    assert resp.relevance.verdict == "off_topic", resp.relevance.verdict
    assert resp.status == "needs_review"
    assert "پیزا" not in (resp.response_text or "")
    assert "wa.me" not in (resp.response_text or "")


@pytest.mark.asyncio
async def test_pipeline_arabic_hours_question(db, user_id, monkeypatch):
    import app.modules.review_engine.service as svc
    import app.modules.llm.gateway as gw

    analysis_payload = {
        "sentiment": "positive", "emotion": "joy",
        "intent": ["question"], "issue_type": None,
        "product_reference": None, "product_reference_en": None,
        "urgency": "low", "customer_request": "هل يفتح المحل بعد الظهر؟",
        "language": "ar",
    }
    gen_text = "نعم، نفتح من 9 صباحًا حتى 5 مساءً."
    fake = _make_fake_complete(analysis_payload, gen_text)
    _install_fake(monkeypatch, fake)

    from app.modules.review_engine.schemas import ReviewEngineRequest
    req = ReviewEngineRequest(
        review_text="هل يفتح المحل بعد الظهر؟", rating=5,
        reviewer_name="Sara", model="openai:gpt-4o-mini", channel="google_review",
    )
    resp = await svc.process_review(req, "t1", db)

    assert resp.analysis.language == "ar"
    assert resp.response_text and "9" in resp.response_text
    assert "wa.me" not in (resp.response_text or "")


@pytest.mark.asyncio
async def test_pipeline_english_praise(db, user_id, monkeypatch):
    import app.modules.review_engine.service as svc
    import app.modules.llm.gateway as gw

    analysis_payload = {
        "sentiment": "very_positive", "emotion": "joy",
        "intent": ["praise"], "issue_type": None,
        "product_reference": None, "product_reference_en": None,
        "urgency": "low", "customer_request": None,
        "language": "en",
    }
    gen_text = "Thanks so much! Really glad you enjoyed it."
    fake = _make_fake_complete(analysis_payload, gen_text)
    _install_fake(monkeypatch, fake)

    from app.modules.review_engine.schemas import ReviewEngineRequest
    req = ReviewEngineRequest(
        review_text="Great service, loved it!", rating=5,
        reviewer_name="John", model="openai:gpt-4o-mini", channel="google_review",
    )
    resp = await svc.process_review(req, "t1", db)

    assert resp.analysis.language == "en"
    assert "Thanks" in (resp.response_text or "")
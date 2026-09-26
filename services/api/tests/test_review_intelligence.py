"""Unit + service tests for AI Review Intelligence (no network).

The LLM is always monkeypatched. Contract/verification/fallback are pure
unit tests; the stored-report flow uses the sqlite-backed db fixture.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.modules.analytics import intelligence_ai as ai


async def _add_insight(db, user_id, row_id, channel_id="ch-test"):
    from app.modules.analytics.models import ReviewInsight

    db.add(ReviewInsight(
        id=row_id, user_id=user_id, channel_id=channel_id,
        review_id=f"r-{row_id}", rating=4, review_text="Good",
        reviewer_name="T", sentiment="positive", sentiment_score=0.8,
        topics=[], products=[], problems=[], enrichment_status="done",
        replied=False, review_updated_at=datetime.now(timezone.utc),
    ))
    await db.commit()


def _rows():
    return [
        {"rating": 4, "text": "I am still using that AI, that's is greatttt.",
         "reviewer": "Syed", "date": "2026-09-09", "sentiment": "neutral",
         "topics": ["quality"], "replied": False},
        {"rating": 5, "text": "Excellent service, quick response.",
         "reviewer": "Sara", "date": "2026-09-06", "sentiment": "positive",
         "topics": ["service"], "replied": True},
    ]


def test_verified_stats_math():
    stats = ai._verified_stats(_rows())
    assert stats == {
        "total": 2, "avg_rating": 4.5,
        "distribution": {5: 1, 4: 1, 3: 0, 2: 0, 1: 0},
        "positive": 2, "neutral": 0, "negative": 0,
        "replied": 1, "unanswered": 1, "response_rate": 50,
    }


def test_verified_stats_empty():
    stats = ai._verified_stats([])
    assert stats["total"] == 0
    assert stats["avg_rating"] == 0.0
    assert stats["response_rate"] == 0


def test_parse_strips_fences():
    raw = '```json\n{"summary": "Good business overall, customers are happy.", "themes": [], "opportunities": [], "strengths": [], "actions": []}\n```'
    parsed = ai._parse_ai_json(raw)
    assert parsed.summary.startswith("Good business")


def test_parse_rejects_garbage():
    with pytest.raises(Exception):
        ai._parse_ai_json("not json at all {{{")


def test_parse_rejects_schema_violation():
    with pytest.raises(Exception):
        ai._parse_ai_json('{"summary": "x", "themes": [{"name": "t"}]}')


def test_verify_clamps_against_stats():
    stats = ai._verified_stats(_rows())
    # Parse-valid but semantically wrong: mentions exceed total, avg needs rounding.
    parsed = ai.AIIntelligence.model_validate({
        "summary": "Everything is amazing and perfect.",
        "themes": [
            {"name": "quality", "mentions": 99, "avg_rating": 4.94,
             "positive_pct": 100, "phrases": ["a", "b", "c"], "trend": "up"},
            {"name": "ghost", "mentions": 0, "avg_rating": 3.0,
             "positive_pct": 50, "phrases": [], "trend": "stable"},
        ],
        "opportunities": [
            {"level": "HIGH", "title": "t1", "detail": "d1", "impact": "HIGH"},
            {"level": "MEDIUM", "title": "t2", "detail": "d2", "impact": "MEDIUM"},
        ],
        "strengths": [
            {"title": "s1", "mentions": 50, "avg": 4.5},
        ],
        "actions": [],
    })
    verified = ai._verify(parsed, stats)
    assert len(verified.themes) == 1  # ghost dropped
    t = verified.themes[0]
    assert t.mentions == 2  # clamped to total
    assert t.avg_rating == 4.9
    assert verified.strengths[0].mentions == 2
    assert len(verified.opportunities) == 2


def test_parse_rejects_overlong_lists():
    with pytest.raises(Exception):
        ai._parse_ai_json('{"summary": "0123456789abcdef", "themes": [], '
                          '"opportunities": [{}, {}, {}, {}, {}], '
                          '"strengths": [], "actions": []}')


def test_fallback_scores_standard_dimensions_from_rows():
    """The offline fallback scores the fixed business dimensions.

    It used to emit raw word-frequency ("version", "things") and bare
    enrichment topic keys, which told an owner nothing. Now it produces the
    standard dimension labels, from the review text.
    """
    fb = ai._fallback_from_rows(_rows())
    names = [t.name for t in fb.themes]
    assert "Responsiveness & Speed" in names   # "quick response" in row 2
    assert "Customer Support & Staff" in names  # "Excellent service" in row 2
    assert fb.summary  # honest offline note, never empty
    # No raw words or bare topic keys leak into the label set.
    assert not any(n in names for n in ("quality", "service", "really", "version", "things"))


def test_fallback_empty_rows():
    fb = ai._fallback_from_rows([])
    assert fb.themes == []
    assert "No reviews" in fb.summary


@pytest.mark.asyncio
async def test_orchestration_ai_path_overrides_numbers(monkeypatch):
    async def _fake_rows(*a, **k):
        return _rows()

    async def _fake_retrieve(*a, **k):
        return {"business_overview": SimpleNamespace(
            has_data=True, rendered="ctx", items=[1, 2])}

    monkeypatch.setattr(ai, "_load_reviews", _fake_rows)
    monkeypatch.setattr(
        "app.modules.retrieval.layer.retrieve_evidence", _fake_retrieve)

    async def _fake_llm(facts, rag_text, model, tenant_id=None):
        assert rag_text == "ctx"
        assert facts["stats"]["total"] == 2
        return ('{"summary": "Customers love the quality and service.", '
                '"themes": [{"name": "quality", "mentions": 5, "avg_rating": 4.0, '
                '"positive_pct": 100, "phrases": ["great"], "trend": "stable"}], '
                '"opportunities": [], "strengths": [], "actions": []}', "gemini:x")

    monkeypatch.setattr(ai, "_call_llm", _fake_llm)
    res = await ai.get_review_intelligence(object(), SimpleNamespace(id="u1"))
    assert res["source"] == "ai"
    assert res["model"] == "gemini:x"
    assert res["rag_used"] is True
    assert res["rag_chunks"] == 2
    # Verified stats win over anything the model implied:
    assert res["stats"]["total"] == 2
    assert res["stats"]["avg_rating"] == 4.5
    assert res["themes"][0]["mentions"] == 2  # clamped from 5


@pytest.mark.asyncio
async def test_orchestration_falls_back_when_llm_down(monkeypatch):
    async def _fake_rows(*a, **k):
        return _rows()

    async def _fake_retrieve(*a, **k):
        return {"business_overview": SimpleNamespace(
            has_data=False, rendered="", items=[])}

    monkeypatch.setattr(ai, "_load_reviews", _fake_rows)
    monkeypatch.setattr(
        "app.modules.retrieval.layer.retrieve_evidence", _fake_retrieve)

    async def _boom(*a, **k):
        raise RuntimeError("ProviderError 403")

    monkeypatch.setattr(ai, "_call_llm", _boom)
    res = await ai.get_review_intelligence(object(), SimpleNamespace(id="u1"))
    assert res["source"] == "fallback"
    assert res["model"] is None
    assert res["stats"]["total"] == 2
    assert res.get("fallback_reason")
    assert any(t["name"] == "Responsiveness & Speed" for t in res["themes"])
    # The scorecard is present even with the LLM down, and is taxonomy-bound.
    assert res["dimensions"]
    assert all(d["standard"] for d in res["dimensions"])
    assert all(d["mentions"] > 0 for d in res["dimensions"])


def _fake_pipeline_result(total=1):
    return {
        "source": "fallback", "model": None,
        "stats": {"total": total, "avg_rating": 4.0,
                  "distribution": {5: 0, 4: total, 3: 0, 2: 0, 1: 0},
                  "positive": total, "neutral": 0, "negative": 0,
                  "replied": 0, "unanswered": total, "response_rate": 0},
        "summary": "Stored summary.",
        "themes": [{"name": "quality", "mentions": total, "avg_rating": 4.0,
                    "positive_pct": 100, "phrases": [], "trend": "stable"}],
        "opportunities": [], "strengths": [], "actions": [],
        "dimensions": [], "competitive": {},
        "rag_used": False, "rag_chunks": 0, "rag_bank": None,
    }


@pytest.mark.asyncio
async def test_stored_report_none_when_never_analyzed(db, user_id):
    assert await ai.get_stored_report(db, user_id, None, 90) is None


@pytest.mark.asyncio
async def test_analyze_stores_and_serves(db, user_id, monkeypatch):
    async def _fake_pipeline(db_, user_, channel_id=None, days=90, databank_id=None,
                             date_from=None, date_to=None):
        return _fake_pipeline_result()

    monkeypatch.setattr(ai, "get_review_intelligence", _fake_pipeline)
    await _add_insight(db, user_id, "ins-serve-1")
    user = SimpleNamespace(id=user_id)
    first = await ai.analyze_and_store(db, user)
    assert first["summary"] == "Stored summary."
    assert first["analyzed_at"]
    assert first["stale"] is False
    assert first["review_count"] == 1

    served = await ai.get_stored_report(db, user_id, None, 90)
    assert served is not None
    assert served["summary"] == "Stored summary."
    assert served["stale"] is False

    # Re-analyze upserts (still exactly one row).
    second = await ai.analyze_and_store(db, user)
    assert second["summary"] == "Stored summary."
    from sqlalchemy import func, select

    from app.modules.analytics.models import ReviewIntelligenceReport

    n = (await db.execute(
        select(func.count()).select_from(ReviewIntelligenceReport)
        .where(ReviewIntelligenceReport.user_id == user_id)
    )).scalar()
    assert n == 1


@pytest.mark.asyncio
async def test_stored_report_goes_stale_on_new_review(db, user_id, monkeypatch):
    from app.modules.analytics.models import ReviewInsight

    async def _fake_pipeline(db_, user_, channel_id=None, days=90, databank_id=None,
                             date_from=None, date_to=None):
        return _fake_pipeline_result()

    monkeypatch.setattr(ai, "get_review_intelligence", _fake_pipeline)
    user = SimpleNamespace(id=user_id)
    await _add_insight(db, user_id, "ins-stale-0")
    await ai.analyze_and_store(db, user)

    await _add_insight(db, user_id, "ins-stale-1")

    served = await ai.get_stored_report(db, user_id, None, 90)
    assert served["stale"] is True
    assert served["current_count"] == served["review_count"] + 1

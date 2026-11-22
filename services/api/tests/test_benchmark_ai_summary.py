"""POST /benchmark/ai-summary: contract shape, LLM green path, fail-open
template fallback and the 10-minute cache.

The LLM seam is the module-level ``complete``/``resolve_tenant_model`` names
in ``app.modules.benchmark.ai`` — the same monkeypatch pattern the agent and
chart tests use. Redis is faked with a dict via monkeypatching the router's
``cache_get``/``cache_set`` (no live Redis in the test loop).
"""
import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest

from app.modules.analytics.models import ReviewInsight
from app.modules.benchmark import ai as benchmark_ai
from app.modules.benchmark import router as benchmark_router
from app.modules.llm.providers.base import LLMResponse, LLMUsage

# No module-level asyncio mark: this file mixes async endpoint tests with
# sync pure-function tests, and marking the sync ones produces
# "marked with asyncio but not async" warnings. Async tests are marked
# individually instead.
AI_URL = "/api/v1/benchmark/ai-summary"
AI_TEXT = "You rank second of two. The rating gap is your biggest lever."
SECRET = "CONFIDENTIAL-REVIEW-BODY"


async def _resolve_ok(db):
    return "fake:model"


def _fake_llm(calls=None, text=AI_TEXT):
    async def _complete(**kwargs):
        if calls is not None:
            calls.append(kwargs)
        return LLMResponse(
            content=text, provider="fake", model="fake", usage=LLMUsage()
        )

    return _complete


async def _boom(**kwargs):
    raise RuntimeError("provider down")


def _bypass_cache(monkeypatch):
    """Pin the cache seam so tests are deterministic.

    A developer machine often runs a live Redis; the endpoint's 10-minute
    entries would otherwise leak between tests (and pytest runs), making the
    fail-open tests return a cached "ai" answer from an earlier run. The
    cache behaviour itself is covered by test_cache_hit_skips_second_llm_call.
    """
    async def _none(key):
        return None

    async def _keep(key, value, ttl=None):
        return None

    monkeypatch.setattr(benchmark_router, "cache_get", _none)
    monkeypatch.setattr(benchmark_router, "cache_set", _keep)


@pytest.mark.asyncio
async def test_ai_summary_green_path_sends_numbers_only(
    client, db, channel_id, user_id, monkeypatch
):
    """Happy path: source "ai", non-empty summary, and the LLM payload is
    numeric summary data — never review text from the database."""
    _bypass_cache(monkeypatch)
    db.add(ReviewInsight(
        id="ri-ai-1", user_id=user_id, channel_id=channel_id,
        review_id="r-ai-1", rating=5, review_text=SECRET,
        review_updated_at=datetime.now(timezone.utc) - timedelta(days=2),
    ))
    await db.commit()

    calls: list[dict] = []
    monkeypatch.setattr(benchmark_ai, "resolve_tenant_model", _resolve_ok)
    monkeypatch.setattr(benchmark_ai, "complete", _fake_llm(calls=calls))

    res = client.post(AI_URL, json={"subjects": [f"own:{channel_id}"]})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["source"] == "ai"
    assert body["summary"] == AI_TEXT
    assert len(calls) == 1, "exactly one LLM call per uncached request"
    sent = json.dumps(calls[0], default=str)
    assert SECRET not in sent, "review text must never leave the database"
    assert "avg_rating" in sent, "the payload carries the headline numbers"


@pytest.mark.asyncio
async def test_llm_failure_fails_open_to_template(client, channel_id, monkeypatch):
    """Any LLM failure is a 200 with a rule-based template, never a 5xx:
    the compare page must always have a summary to render."""
    _bypass_cache(monkeypatch)
    monkeypatch.setattr(benchmark_ai, "resolve_tenant_model", _resolve_ok)
    monkeypatch.setattr(benchmark_ai, "complete", _boom)
    res = client.post(AI_URL, json={"subjects": [f"own:{channel_id}"]})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["source"] == "template"
    assert body["summary"].strip()


@pytest.mark.asyncio
async def test_llm_timeout_fails_open_to_template(client, channel_id, monkeypatch):
    async def _slow(**kwargs):
        raise asyncio.TimeoutError()

    _bypass_cache(monkeypatch)
    monkeypatch.setattr(benchmark_ai, "resolve_tenant_model", _resolve_ok)
    monkeypatch.setattr(benchmark_ai, "complete", _slow)
    res = client.post(AI_URL, json={"subjects": [f"own:{channel_id}"]})
    assert res.status_code == 200, res.text
    assert res.json()["source"] == "template"


@pytest.mark.asyncio
async def test_no_enabled_model_fails_open_to_template(
    client, channel_id, monkeypatch
):
    async def _no_model(db):
        raise ValueError("No AI model is enabled by your administrator.")

    _bypass_cache(monkeypatch)
    monkeypatch.setattr(benchmark_ai, "resolve_tenant_model", _no_model)
    monkeypatch.setattr(benchmark_ai, "complete", _boom)
    res = client.post(AI_URL, json={"subjects": [f"own:{channel_id}"]})
    assert res.status_code == 200, res.text
    assert res.json()["source"] == "template"


@pytest.mark.asyncio
async def test_unknown_subject_is_not_an_error(client, monkeypatch):
    """Unknown subjects ride through compare_subjects as unavailable records;
    with no data at all the answer is the template's not-enough-data line."""
    _bypass_cache(monkeypatch)
    monkeypatch.setattr(benchmark_ai, "resolve_tenant_model", _resolve_ok)
    monkeypatch.setattr(benchmark_ai, "complete", _boom)
    res = client.post(AI_URL, json={"subjects": ["unknown:zzz"]})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["source"] == "template"
    assert "not enough" in body["summary"].lower()


@pytest.mark.asyncio
async def test_subject_bounds_enforced(client):
    assert client.post(AI_URL, json={"subjects": []}).status_code == 422
    seven = client.post(
        AI_URL, json={"subjects": [f"own:n{i}" for i in range(7)]}
    )
    assert seven.status_code == 422
    # Per-item bound: one oversized key is rejected, a key at the limit passes.
    too_long = "own:" + "x" * 255  # 259 chars > 255
    assert client.post(AI_URL, json={"subjects": [too_long]}).status_code == 422
    at_limit = "own:" + "x" * 251  # exactly 255
    at_limit_res = client.post(AI_URL, json={"subjects": [at_limit]})
    assert at_limit_res.status_code == 200, at_limit_res.text


@pytest.mark.asyncio
async def test_cache_hit_skips_second_llm_call(client, db, channel_id, user_id,
                                               monkeypatch):
    """Cache is keyed on sha1(sorted subjects): a reordered repeat is a hit."""
    from app.modules.benchmark import places as places_module
    from app.modules.benchmark import service as bench_service

    await bench_service.save_place(db, user_id, place_id="ai-1", label="AI Rival")

    async def _fake_get_place(place_id, **kwargs):
        return {"place_id": place_id, "name": place_id, "address": None,
                "rating": 4.2, "review_count": 30, "types": [], "reviews": []}

    monkeypatch.setattr(places_module, "get_place", _fake_get_place)

    store: dict[str, str] = {}

    async def fake_get(key):
        return store.get(key)

    async def fake_set(key, value, ttl=None):
        store[key] = value

    monkeypatch.setattr(benchmark_router, "cache_get", fake_get)
    monkeypatch.setattr(benchmark_router, "cache_set", fake_set)

    calls: list[dict] = []
    monkeypatch.setattr(benchmark_ai, "resolve_tenant_model", _resolve_ok)
    monkeypatch.setattr(benchmark_ai, "complete", _fake_llm(calls=calls))

    first = client.post(
        AI_URL, json={"subjects": [f"own:{channel_id}", "saved:ai-1"]}
    )
    second = client.post(
        AI_URL, json={"subjects": ["saved:ai-1", f"own:{channel_id}"]}
    )
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert second.json() == first.json()
    assert len(calls) == 1, "the reordered repeat must be served from cache"
    assert first.json()["source"] == "ai"


# ── Template fallback: useful sentences from the numbers alone ─────────────

def test_payload_metrics_match_summary_semantics():
    """Per-subject numbers must derive like the distribution does: velocity
    from the review windows, sentiment from facts — never raw-key lookups."""
    subject = {
        "available": True,
        "key": "own:1",
        "name": "Mine",
        "metrics": {"reviews_last_year": 24, "avg_rating": 4.0},
        "facts": {"positive_pct": 80},
    }
    payload = benchmark_ai.build_numeric_payload([subject], ["own:1"])
    subj = payload["subjects"][0]
    assert subj["own"] is True
    assert subj["metrics"]["reviews_per_month"] == 2.0  # 24/12 via summary
    assert subj["metrics"]["avg_rating"] == 4.0
    assert subj["metrics"]["positive_pct"] == 80.0


def test_template_summary_uses_rank_leader_and_gap():
    payload = {
        "north_star": {
            "rank": 2,
            "of": 4,
            "own": {"key": "own:1", "name": "Mine"},
            "leader": {"key": "saved:2", "name": "Rival"},
            "gaps": {
                "avg_rating": 0.6,
                "reviews_per_month": None,
                "total_reviews": None,
                "positive_pct": None,
            },
        },
        "distribution": {},
        "subjects": [],
    }
    text = benchmark_ai.template_summary(payload)
    assert "Mine" in text and "Rival" in text
    assert "2 of 4" in text
    assert "rating" in text
    assert len(text) <= 300


def test_template_summary_without_own_subject_describes_bench():
    payload = {
        "north_star": None,
        "distribution": {
            "avg_rating": {
                "best": {"name": "Leader", "value": 4.6},
                "worst": {"name": "Trailer", "value": 3.1},
            },
        },
        "subjects": [],
    }
    text = benchmark_ai.template_summary(payload)
    assert "Leader" in text and "Trailer" in text
    assert len(text) <= 300


def test_template_summary_empty_payload_is_still_useful():
    text = benchmark_ai.template_summary({})
    assert text.strip()
    assert len(text) <= 300

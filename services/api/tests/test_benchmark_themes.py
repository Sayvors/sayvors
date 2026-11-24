"""Dynamic benchmark themes: bounded samples, durable jobs and API contract."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import OperationalError

from app.modules.analytics.models import ReviewInsight
from app.modules.benchmark import service as bench_service
from app.modules.benchmark import theme_jobs, theme_service
from app.modules.benchmark.models import BenchmarkThemeAnalysis
from app.modules.jobs.models import Job
from app.modules.jobs.service import claim_due_jobs
from app.modules.llm.providers.base import LLMResponse, LLMUsage, ProviderError

TENANT = "test-user-0000-0000-0000-000000000001"
OTHER_TENANT = "test-user-0000-0000-0000-000000000002"


async def _resolve_ok(_db):
    return "fake:model"


def _response(text: str):
    return LLMResponse(content=text, provider="fake", model="fake", usage=LLMUsage())


async def _seed_own(db, user_id, channel_id, count=3):
    rows = []
    for index in range(count):
        published = datetime.now(timezone.utc) - timedelta(minutes=index)
        rows.append(ReviewInsight(
            id=f"theme-review-{index}",
            user_id=user_id,
            channel_id=channel_id,
            review_id=f"own-review-{index}",
            rating=5 if index < 2 else 1,
            review_text=f"Helpful staff and fast service review {index}",
            reviewer_name=f"Author {index}",
            reviewer_photo_url=f"https://example.com/{index}.jpg",
            review_url=f"https://www.google.com/maps/review/{index}",
            sentiment="positive" if index < 2 else "negative",
            review_updated_at=published,
        ))
    db.add_all(rows)
    await db.commit()


async def _claimed_theme_job(db):
    jobs = await claim_due_jobs(db, lane="bulk", worker_id="theme-test", limit=10)
    await db.commit()
    return next(job for job in jobs if job.job_type == "benchmark.theme_extract")


@pytest.mark.asyncio
async def test_saved_sample_is_scoped_bounded_and_hash_stable(db, user_id, other_user_id):
    reviews = [
        {
            "review_id": f"saved-{index}",
            "review_url": f"https://www.google.com/maps/review/{index}",
            "text": "x" * 900 + str(index),
            "rating": 5,
            "author": f"Author {index}",
            "author_photo": f"https://example.com/{index}.jpg",
            "publish_time": "2026-11-01T00:00:00Z",
        }
        for index in range(55)
    ]
    saved = await bench_service.save_place(db, TENANT, place_id="mine", label="Mine")
    saved.reviews = reviews
    await bench_service.save_place(db, OTHER_TENANT, place_id="theirs", label="Theirs")
    await db.commit()

    subject = await theme_service.build_subject_sample(db, TENANT, "saved:mine")
    assert subject is not None
    assert subject["subject_id"] == saved.id
    assert subject["name"] == "Mine"
    assert len(subject["reviews"]) == 50
    assert all(len(review["text"]) <= 600 for review in subject["reviews"])
    assert subject["reviews"][0]["review_id"] == "saved-0"
    assert subject["reviews"][0]["review_url"].endswith("/0")
    assert subject["sample_hash"] == theme_service.hash_sample(subject["reviews"])
    assert await theme_service.build_subject_sample(db, TENANT, "saved:theirs") is None
    assert await theme_service.build_subject_sample(db, TENANT, "own:missing") is None


@pytest.mark.asyncio
async def test_own_sample_is_scoped_bounded_and_missing_ids_are_deterministic(
    db, user_id, channel_id
):
    await _seed_own(db, user_id, channel_id, count=55)
    subject = await theme_service.build_subject_sample(db, TENANT, f"own:{channel_id}")
    assert subject is not None
    assert subject["subject_id"] == channel_id
    assert len(subject["reviews"]) == 50
    assert subject["reviews"][0]["review_id"] == "own-review-0"
    assert await theme_service.build_subject_sample(db, OTHER_TENANT, f"own:{channel_id}") is None

    raw = [{"text": "No source id", "rating": 4, "author": "A"}]
    first = theme_service.normalize_reviews(raw)
    second = theme_service.normalize_reviews(raw)
    assert first[0]["review_id"].startswith("synthetic:")
    assert first == second


@pytest.mark.asyncio
async def test_enqueue_is_idempotent_and_ready_hash_is_reused(db, user_id, channel_id):
    await _seed_own(db, user_id, channel_id)
    subject = await theme_service.build_subject_sample(db, TENANT, f"own:{channel_id}")

    first = await theme_service.ensure_theme_analysis(db, TENANT, f"own:{channel_id}")
    second = await theme_service.ensure_theme_analysis(db, TENANT, f"own:{channel_id}")
    assert first.id == second.id
    assert first.job_id == second.job_id
    assert first.sample_hash == subject["sample_hash"]
    assert first.sample_json == subject["reviews"]
    assert first.status == "pending"
    assert await db.scalar(select(func.count(Job.id))) == 1
    assert await db.scalar(select(func.count(BenchmarkThemeAnalysis.id))) == 1

    first.status = "ready"
    first.themes = [{"label": "helpful staff"}]
    await db.commit()
    ready = await theme_service.ensure_theme_analysis(db, TENANT, f"own:{channel_id}")
    assert ready.id == first.id
    assert ready.job_id == first.job_id
    assert await db.scalar(select(func.count(Job.id))) == 1


@pytest.mark.asyncio
async def test_retry_replaces_terminal_error_and_stale_ready_jobs(db, user_id, channel_id):
    await _seed_own(db, user_id, channel_id)
    analysis = await theme_service.ensure_theme_analysis(db, TENANT, f"own:{channel_id}")
    original_job = analysis.job_id
    analysis.status = "failed"
    analysis.error = "old failure"
    await db.commit()

    cooling = await theme_service.ensure_theme_analysis(
        db, TENANT, f"own:{channel_id}", retry=True
    )
    assert cooling.job_id == original_job
    assert cooling.status == "failed"

    analysis.updated_at = datetime.now(timezone.utc) - timedelta(seconds=301)
    await db.commit()
    retried = await theme_service.ensure_theme_analysis(
        db, TENANT, f"own:{channel_id}", retry=True
    )
    assert retried.id == analysis.id
    assert retried.job_id != original_job
    retried_job = retried.job_id
    assert retried.status == "pending"
    assert retried.error is None

    retried.status = "ready"
    retried.themes = [{"label": "old"}]
    retried.updated_at = datetime.now(timezone.utc) - timedelta(seconds=301)
    await db.commit()
    assert retried.updated_at < datetime.now(timezone.utc) - timedelta(seconds=300)
    changed = await db.get(ReviewInsight, "theme-review-0")
    changed.review_text = "A newly synced review changes the sample"
    await db.commit()
    new_sample = await theme_service.build_subject_sample(db, TENANT, f"own:{channel_id}")
    assert new_sample["sample_hash"] != retried.sample_hash
    stale = await theme_service.ensure_theme_analysis(db, TENANT, f"own:{channel_id}")
    assert stale.job_id != retried_job, (
        f"status={stale.status} hash={stale.sample_hash} "
        f"expected={new_sample['sample_hash']} updated={stale.updated_at}"
    )
    assert stale.status == "pending"
    assert await db.scalar(select(func.count(Job.id))) == 3


def test_response_mapping_quotes_sentiment_and_neutral_omission():
    reviews = [
        {"review_id": "r1", "text": "Helpful staff were great", "rating": 5,
         "author": "A", "author_photo": "https://example.com/a.jpg",
         "reviewed_at": "2026-11-01T00:00:00Z",
         "review_url": "https://www.google.com/maps/review/r1"},
        {"review_id": "r2", "text": "Fast service every time", "rating": 5,
         "author": "B", "review_url": None},
        {"review_id": "r3", "text": "Calm ambiance", "rating": 3,
         "author": "C", "review_url": None},
        {"review_id": "r4", "text": "The team was great", "rating": 5,
         "author": "D", "review_url": None},
    ]

    def theme(label, mentions, positive, negative, review_id, normalized=None):
        return {
            "label": label, "normalized": normalized or label,
            "mentions": mentions, "sample_size": 4, "pct": mentions * 25.0,
            "positive_mentions": positive, "negative_mentions": negative,
            "neutral_mentions": mentions - positive - negative,
            "examples": [{"review_id": review_id, "text": next(
                review["text"] for review in reviews if review["review_id"] == review_id
            )}],
        }

    payload = theme_service.assemble_theme_response([{
        "key": "own:mine", "name": "Mine", "kind": "own", "status": "ready",
        "sample_size": 4, "sample_hash": "a" * 64, "analyzed_at": "2026-11-24T00:00:00Z",
        "source": "llm", "reviews": reviews,
        "themes": [
            theme("helpful staff", 2, 1, 1, "r1"),
            theme("fast service", 4, 3, 1, "r2"),
            theme("calm ambiance", 2, 0, 0, "r3"),
            theme("service quality", 2, 2, 0, "r4"),
        ],
    }])
    rows = {row["key"]: row for row in payload["rows"]}
    assert "calm ambiance" not in rows
    assert rows["helpful staff"]["sentiment"] == "mixed"
    assert rows["fast service"]["sentiment"] == "positive"
    quote = rows["helpful staff"]["cells"]["own:mine"]["quotes"][0]
    assert quote["quote"] == "Helpful staff"
    assert quote["review_text"] == "Helpful staff were great"
    assert quote["quote"] in quote["review_text"]
    assert quote["review_url"] == "https://www.google.com/maps/review/r1"
    fallback = rows["service quality"]["cells"]["own:mine"]["quotes"][0]
    assert fallback["quote"] == fallback["review_text"] == "The team was great"
    assert fallback["review_url"] is None


@pytest.mark.asyncio
async def test_themes_api_pending_ready_error_retry_and_bounds(
    client, db, user_id, channel_id
):
    from app.modules.benchmark.theme_extraction import extract_local_themes

    await _seed_own(db, user_id, channel_id)
    params = [("subjects", f"own:{channel_id}"), ("subjects", "bogus:x")]
    pending = client.get("/api/v1/benchmark/themes", params=params)
    assert pending.status_code == 200, pending.text
    body = pending.json()
    assert [subject["status"] for subject in body["subjects"]] == ["pending", "unavailable"]
    assert body["rows"] == []
    assert body["subjects"][0]["sample_size"] == 3
    assert len(body["subjects"][0]["sample_hash"]) == 64
    assert await db.scalar(select(func.count(Job.id))) == 1

    repeat = client.get("/api/v1/benchmark/themes", params=params)
    assert repeat.json() == body
    assert await db.scalar(select(func.count(Job.id))) == 1

    analysis = await db.scalar(select(BenchmarkThemeAnalysis))
    analysis.status = "ready"
    analysis.source = "local"
    analysis.themes = extract_local_themes(analysis.sample_json)
    await db.commit()
    ready = client.get("/api/v1/benchmark/themes", params=params)
    assert ready.status_code == 200, ready.text
    ready_body = ready.json()
    assert ready_body["subjects"][0]["status"] == "ready"
    assert ready_body["subjects"][0]["source"] == "local"
    assert ready_body["rows"]
    for row in ready_body["rows"]:
        assert row["sentiment"] in {"positive", "negative", "mixed"}
        for cell in row["cells"].values():
            for quote in cell["quotes"]:
                assert quote["quote"] in quote["review_text"]

    analysis.status = "failed"
    analysis.error = "provider unavailable"
    await db.commit()
    failed = client.get("/api/v1/benchmark/themes", params=params)
    assert failed.json()["subjects"][0]["status"] == "error"
    assert failed.json()["subjects"][0]["error_code"] == "analysis_failed"
    cooling = client.post("/api/v1/benchmark/themes/retry", json={"subjects": [f"own:{channel_id}"]})
    assert cooling.status_code == 200, cooling.text
    assert cooling.json()["subjects"][0]["status"] == "error"
    assert await db.scalar(select(func.count(Job.id))) == 1

    analysis.updated_at = datetime.now(timezone.utc) - timedelta(seconds=301)
    await db.commit()
    retried = client.post("/api/v1/benchmark/themes/retry", json={"subjects": [f"own:{channel_id}"]})
    assert retried.json()["subjects"][0]["status"] == "pending"
    assert await db.scalar(select(func.count(Job.id))) == 2

    current = await db.scalar(select(BenchmarkThemeAnalysis))
    current.status = "ready"
    await db.commit()
    no_repeat = client.post("/api/v1/benchmark/themes/retry", json={"subjects": [f"own:{channel_id}"]})
    assert no_repeat.json()["subjects"][0]["status"] == "ready"
    assert await db.scalar(select(func.count(Job.id))) == 2
    assert client.get("/api/v1/benchmark/themes").status_code == 422
    assert client.get(
        "/api/v1/benchmark/themes",
        params={"subjects": "own:" + "x" * 255},
    ).status_code == 422
    assert client.get(
        "/api/v1/benchmark/themes",
        params=[("subjects", f"own:n{i}") for i in range(7)],
    ).status_code == 422


@pytest.mark.asyncio
async def test_handler_rejects_wrong_tenant_job_and_hash(db, user_id, channel_id, monkeypatch):
    await _seed_own(db, user_id, channel_id)
    analysis = await theme_service.ensure_theme_analysis(db, TENANT, f"own:{channel_id}")
    job = await _claimed_theme_job(db)

    async def forbidden(**_kwargs):
        raise AssertionError("LLM must not run for a guarded job")

    monkeypatch.setattr(theme_jobs, "resolve_tenant_model", forbidden)
    monkeypatch.setattr(theme_jobs, "complete", forbidden)
    variants = [
        SimpleNamespace(id=job.id, tenant_id=OTHER_TENANT, payload=job.payload),
        SimpleNamespace(id="wrong-job", tenant_id=TENANT, payload=job.payload),
        SimpleNamespace(id=job.id, tenant_id=TENANT, payload={**job.payload, "sample_hash": "b" * 64}),
    ]
    for variant in variants:
        result = await theme_jobs.handle_benchmark_theme_extract(variant, db)
        assert result["status"] == "skipped"
    await db.refresh(analysis)
    assert analysis.status == "pending"


@pytest.mark.asyncio
async def test_handler_llm_green_path_uses_bounded_prompt_and_real_evidence(
    db, user_id, channel_id, monkeypatch
):
    await _seed_own(db, user_id, channel_id, count=2)
    analysis = await theme_service.ensure_theme_analysis(db, TENANT, f"own:{channel_id}")
    job = await _claimed_theme_job(db)
    calls = []

    async def fake_complete(**kwargs):
        calls.append(kwargs)
        return _response(json.dumps({"themes": [{
            "label": "helpful staff", "mentions": 2, "review_indices": [0, 1],
        }]}))

    monkeypatch.setattr(theme_jobs, "resolve_tenant_model", _resolve_ok)
    monkeypatch.setattr(theme_jobs, "complete", fake_complete)
    result = await theme_jobs.handle_benchmark_theme_extract(job, db)
    assert result["status"] == "ready"
    await db.refresh(analysis)
    assert analysis.status == "ready"
    assert analysis.source == "llm"
    assert analysis.model == "fake:model"
    assert analysis.error is None
    assert analysis.themes[0]["mentions"] == 2
    assert len(calls) == 1
    call = calls[0]
    assert call["tenant_id"] == TENANT
    assert call["purpose"] == "benchmark.theme_extract"
    assert call["temperature"] == 0.1
    assert 1000 <= call["max_tokens"] <= 1500
    prompt = json.loads(call["messages"][0].content)
    assert len(prompt["reviews"]) == 2
    assert set(prompt["reviews"][0]) == {"index", "rating", "sentiment", "text"}
    assert "review_id" not in prompt["reviews"][0]
    assert prompt["reviews"][0]["index"] == 0

    payload = theme_service.assemble_theme_response([{
        "key": f"own:{channel_id}", "name": "Test Burgers", "kind": "own",
        "status": "ready", "sample_size": 2, "sample_hash": analysis.sample_hash,
        "analyzed_at": analysis.updated_at.isoformat(), "source": "llm",
        "reviews": analysis.sample_json, "themes": analysis.themes,
    }])
    quote = payload["rows"][0]["cells"][f"own:{channel_id}"]["quotes"][0]
    assert quote["quote"] == "Helpful staff"
    assert quote["review_url"] == "https://www.google.com/maps/review/0"
    assert quote["quote"] in quote["review_text"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("content", "expected_source"),
    [
        ('```json\n{"themes":[{"label":"helpful staff","mentions":2,"review_indices":[0,1]}]}\n```', "llm"),
        ("not valid json", "local"),
        ('{"themes":[{"label":"helpful staff","mentions":99,"review_indices":[0,1]}]}', "local"),
    ],
)
async def test_handler_fences_parse_and_bad_output_falls_back_locally(
    db, user_id, channel_id, monkeypatch, content, expected_source
):
    await _seed_own(db, user_id, channel_id, count=2)
    analysis = await theme_service.ensure_theme_analysis(db, TENANT, f"own:{channel_id}")
    job = await _claimed_theme_job(db)
    monkeypatch.setattr(theme_jobs, "resolve_tenant_model", _resolve_ok)

    async def fake_complete(**_kwargs):
        return _response(content)

    monkeypatch.setattr(theme_jobs, "complete", fake_complete)
    result = await theme_jobs.handle_benchmark_theme_extract(job, db)
    assert result["status"] == "ready"
    await db.refresh(analysis)
    assert analysis.source == expected_source
    assert analysis.themes
    assert analysis.error is None


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["provider", "budget", "model"])
async def test_handler_provider_budget_and_model_failures_use_local_fallback(
    db, user_id, channel_id, monkeypatch, failure
):
    await _seed_own(db, user_id, channel_id, count=2)
    analysis = await theme_service.ensure_theme_analysis(db, TENANT, f"own:{channel_id}")
    job = await _claimed_theme_job(db)

    async def failing_complete(**_kwargs):
        if failure == "budget":
            raise ProviderError("budget", "wallet exhausted", 402)
        raise ProviderError("fake", "provider unavailable", 502)

    async def failing_model(_db):
        raise ValueError("No AI model enabled")

    monkeypatch.setattr(theme_jobs, "resolve_tenant_model", failing_model if failure == "model" else _resolve_ok)
    monkeypatch.setattr(theme_jobs, "complete", failing_complete)
    result = await theme_jobs.handle_benchmark_theme_extract(job, db)
    assert result["status"] == "ready"
    await db.refresh(analysis)
    assert analysis.status == "ready"
    assert analysis.source == "local"
    assert analysis.themes
    assert analysis.error is None


@pytest.mark.asyncio
async def test_completed_analysis_does_not_repeat_llm(db, user_id, channel_id, monkeypatch):
    await _seed_own(db, user_id, channel_id, count=2)
    analysis = await theme_service.ensure_theme_analysis(db, TENANT, f"own:{channel_id}")
    job = await _claimed_theme_job(db)
    analysis.status = "ready"
    analysis.themes = [{"label": "already done"}]
    await db.commit()

    async def forbidden(**_kwargs):
        raise AssertionError("completed analysis must not call the LLM")

    monkeypatch.setattr(theme_jobs, "resolve_tenant_model", forbidden)
    monkeypatch.setattr(theme_jobs, "complete", forbidden)
    result = await theme_jobs.handle_benchmark_theme_extract(job, db)
    assert result["status"] == "already_ready"
    await db.refresh(analysis)
    assert analysis.themes == [{"label": "already done"}]


@pytest.mark.asyncio
async def test_handler_never_overwrites_a_newer_sample(db, user_id, channel_id, monkeypatch):
    await _seed_own(db, user_id, channel_id, count=2)
    analysis = await theme_service.ensure_theme_analysis(db, TENANT, f"own:{channel_id}")
    job = await _claimed_theme_job(db)

    async def replace_sample(**_kwargs):
        analysis.sample_hash = "b" * 64
        analysis.job_id = "newer-job"
        analysis.status = "pending"
        analysis.themes = [{"label": "newer"}]
        await db.commit()
        return _response("not json")

    monkeypatch.setattr(theme_jobs, "resolve_tenant_model", _resolve_ok)
    monkeypatch.setattr(theme_jobs, "complete", replace_sample)
    result = await theme_jobs.handle_benchmark_theme_extract(job, db)
    assert result["status"] == "skipped"
    await db.refresh(analysis)
    assert analysis.sample_hash == "b" * 64
    assert analysis.job_id == "newer-job"
    assert analysis.status == "pending"
    assert analysis.themes == [{"label": "newer"}]


@pytest.mark.asyncio
async def test_handler_database_errors_propagate(db, user_id, channel_id, monkeypatch):
    await _seed_own(db, user_id, channel_id, count=2)
    analysis = await theme_service.ensure_theme_analysis(db, TENANT, f"own:{channel_id}")
    job = await _claimed_theme_job(db)

    async def db_failure(**_kwargs):
        raise OperationalError("SELECT", {}, Exception("database unavailable"))

    monkeypatch.setattr(theme_jobs, "resolve_tenant_model", _resolve_ok)
    monkeypatch.setattr(theme_jobs, "complete", db_failure)
    with pytest.raises(OperationalError, match="database unavailable"):
        await theme_jobs.handle_benchmark_theme_extract(job, db)
    await db.refresh(analysis)
    assert analysis.status == "running"


@pytest.mark.asyncio
async def test_handler_persists_failed_when_local_extraction_fails(
    db, user_id, channel_id, monkeypatch
):
    await _seed_own(db, user_id, channel_id, count=1)
    analysis = await theme_service.ensure_theme_analysis(db, TENANT, f"own:{channel_id}")
    job = await _claimed_theme_job(db)

    async def forbidden(**_kwargs):
        raise AssertionError("one review must not call the LLM")

    def broken_local(_reviews):
        raise RuntimeError("local extractor failed")

    monkeypatch.setattr(theme_jobs, "resolve_tenant_model", forbidden)
    monkeypatch.setattr(theme_jobs, "complete", forbidden)
    monkeypatch.setattr(theme_jobs, "extract_local_themes", broken_local)
    with pytest.raises(RuntimeError, match="local extractor failed"):
        await theme_jobs.handle_benchmark_theme_extract(job, db)
    await db.refresh(analysis)
    assert analysis.status == "failed"
    assert analysis.error == "local extractor failed"


@pytest.mark.asyncio
async def test_delete_saved_removes_theme_analysis(db, user_id):
    saved = await bench_service.save_place(db, TENANT, place_id="delete-me", label="Delete")
    saved.reviews = [
        {"review_id": "r1", "text": "Helpful staff", "rating": 5},
        {"review_id": "r2", "text": "Helpful staff again", "rating": 5},
    ]
    await db.commit()
    analysis = await theme_service.ensure_theme_analysis(db, TENANT, "saved:delete-me")
    assert await bench_service.delete_saved(db, TENANT, "delete-me") is True
    assert await db.get(BenchmarkThemeAnalysis, analysis.id) is None

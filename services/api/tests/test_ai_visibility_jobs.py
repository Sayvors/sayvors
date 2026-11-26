"""Durable grounded-research pipeline."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.modules.ai_visibility import jobs, research
from app.modules.ai_visibility.models import (
    AiVisibilityPrompt,
    AiVisibilityRun,
    AiVisibilitySource,
)
from app.modules.jobs.models import Job


async def _seed(db, user_id, channel_id):
    prompt = AiVisibilityPrompt(
        tenant_id=user_id,
        channel_id=channel_id,
        title="Coffee",
        prompt_text="Best coffee near Malqa",
        normalized_prompt_hash="d" * 64,
        intent="discovery",
        created_by=user_id,
    )
    db.add(prompt)
    await db.flush()
    run = AiVisibilityRun(
        tenant_id=user_id,
        channel_id=channel_id,
        prompt_id=prompt.id,
        prompt_snapshot=prompt.prompt_text,
        locale="en",
        status="queued",
    )
    db.add(run)
    await db.flush()
    job = Job(
        id="job-1",
        tenant_id=user_id,
        job_type="ai_visibility.research",
        lane="bulk",
        status="running",
        payload={"run_id": run.id},
        lane_key="ai-visibility-test",
        subject_type="ai_visibility_run",
        subject_id=run.id,
        lease_owner="worker-1",
        lease_expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
    )
    run.job_id = job.id
    db.add(job)
    await db.commit()
    return run, job


def test_source_payload_preserves_original_citation_labels():
    rows = [
        AiVisibilitySource(position=1, url="https://b.example", excerpt="B"),
        AiVisibilitySource(position=2, url="https://c.example", excerpt="C"),
    ]
    payload = jobs._source_payload(rows)
    assert [row["label"] for row in payload] == ["S2", "S3"]


@pytest.mark.asyncio
async def test_job_completes_with_validated_brief(
    db, user_id, channel_id, monkeypatch
):
    run, job = await _seed(db, user_id, channel_id)

    async def _search(_tenant, _query):
        return [
            SimpleNamespace(url="https://a.example", title="A", snippet=""),
            SimpleNamespace(url="https://b.example", title="B", snippet=""),
        ]

    async def _fetch(_db, run_id, rows):
        return [
            AiVisibilitySource(
                run_id=run_id,
                position=0,
                url="https://a.example",
                canonical_url="https://a.example",
                title="A",
                excerpt="Acme Coffee is recommended.",
            ),
            AiVisibilitySource(
                run_id=run_id,
                position=1,
                url="https://b.example",
                canonical_url="https://b.example",
                title="B",
                excerpt="Acme Coffee serves fresh coffee.",
            ),
        ]

    payload = research.ResearchPayload(
        answer="Acme Coffee is recommended [S1].",
        claims=[
            research.ResearchClaim(
                claim="Acme Coffee is recommended",
                quote="Acme Coffee is recommended",
                source_ids=["S1"],
                status="supported",
            )
        ],
        mentioned=True,
        cited=False,
        recommended=True,
        incorrect=False,
    )

    async def _complete(_db, **_kwargs):
        await db.refresh(run)
        await db.refresh(job)
        assert run.status == "writing"
        assert run.failure_code == jobs.LLM_PENDING_FAILURE_CODE
        expires = job.lease_expires_at
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        assert expires > datetime.now(timezone.utc) + timedelta(minutes=5)
        return "fake:model", payload

    async def _facts(*_args):
        return {"name": "Acme Coffee", "website": "https://acme.example"}

    monkeypatch.setattr(jobs.search, "search_public_web", _search)
    monkeypatch.setattr(jobs.sources, "fetch_sources", _fetch)
    monkeypatch.setattr(jobs.research, "complete_research", _complete)
    monkeypatch.setattr(jobs, "load_branch_facts", _facts)

    result = await jobs.handle_research(job, db)
    await db.refresh(run)
    assert result["status"] == "completed", run.error
    assert run.status == "completed"
    assert run.mentioned is True
    assert run.claims_json[0]["status"] == "supported"
    assert run.actions_json


@pytest.mark.asyncio
async def test_reclaimed_job_reuses_committed_source_snapshots(
    db, user_id, channel_id, monkeypatch
):
    run, job = await _seed(db, user_id, channel_id)
    run.status = "fetching"
    db.add_all(
        [
            AiVisibilitySource(
                run_id=run.id,
                position=0,
                url="https://a.example",
                canonical_url="https://a.example",
                title="A",
                excerpt="Acme Coffee is recommended.",
            ),
            AiVisibilitySource(
                run_id=run.id,
                position=1,
                url="https://b.example",
                canonical_url="https://b.example",
                title="B",
                excerpt="Acme Coffee serves fresh coffee.",
            ),
        ]
    )
    await db.commit()
    called = []

    async def _search(*_args):
        called.append("search")
        return []

    async def _fetch(*_args):
        called.append("fetch")
        return []

    async def _complete(*_args, **_kwargs):
        called.append("llm")
        return "fake:model", research.ResearchPayload(
            answer="Acme Coffee is recommended [S1].",
            claims=[
                research.ResearchClaim(
                    claim="Acme Coffee is recommended",
                    quote="Acme Coffee is recommended",
                    source_ids=["S1"],
                    status="supported",
                )
            ],
            mentioned=True,
            cited=False,
            recommended=True,
            incorrect=False,
        )

    async def _facts(*_args):
        return {"name": "Acme Coffee"}

    monkeypatch.setattr(jobs.search, "search_public_web", _search)
    monkeypatch.setattr(jobs.sources, "fetch_sources", _fetch)
    monkeypatch.setattr(jobs.research, "complete_research", _complete)
    monkeypatch.setattr(jobs, "load_branch_facts", _facts)

    result = await jobs.handle_research(job, db)
    assert result["status"] == "completed"
    assert called == ["llm"]


@pytest.mark.asyncio
async def test_reclaimed_job_does_not_repeat_an_uncertain_llm_call(
    db, user_id, channel_id, monkeypatch
):
    run, job = await _seed(db, user_id, channel_id)
    run.status = "writing"
    run.failure_code = "llm_call_in_progress"
    db.add_all(
        [
            AiVisibilitySource(
                run_id=run.id,
                position=position,
                url=f"https://{label}.example",
                canonical_url=f"https://{label}.example",
                title=label,
                excerpt="Acme Coffee is recommended.",
            )
            for position, label in enumerate(("a", "b"))
        ]
    )
    await db.commit()
    called = []

    async def _complete(*_args, **_kwargs):
        called.append("llm")
        raise AssertionError("an uncertain LLM call must not be repeated")

    async def _facts(*_args):
        return {"name": "Acme Coffee"}

    monkeypatch.setattr(jobs.research, "complete_research", _complete)
    monkeypatch.setattr(jobs, "load_branch_facts", _facts)

    result = await jobs.handle_research(job, db)
    await db.refresh(run)
    assert result["status"] == "ambiguous"
    assert run.status == "ambiguous"
    assert run.failure_code == "llm_outcome_unknown"
    assert called == []


@pytest.mark.asyncio
async def test_job_rechecks_run_immediately_before_llm(
    db, user_id, channel_id, monkeypatch
):
    run, job = await _seed(db, user_id, channel_id)
    db.add_all(
        [
            AiVisibilitySource(
                run_id=run.id,
                position=position,
                url=f"https://{label}.example",
                canonical_url=f"https://{label}.example",
                title=label,
                excerpt="Acme Coffee is recommended.",
            )
            for position, label in enumerate(("a", "b"))
        ]
    )
    await db.commit()
    called = []

    async def _facts(_db, _tenant, _channel):
        await db.delete(run)
        await db.commit()
        return {"name": "Acme Coffee"}

    async def _complete(*_args, **_kwargs):
        called.append("llm")
        raise AssertionError("deleted runs must not reach the LLM")

    monkeypatch.setattr(jobs, "load_branch_facts", _facts)
    monkeypatch.setattr(jobs.research, "complete_research", _complete)

    result = await jobs.handle_research(job, db)
    assert result["status"] == "cancelled"
    assert called == []


@pytest.mark.asyncio
async def test_post_llm_status_persistence_failure_is_ambiguous(
    db, user_id, channel_id, monkeypatch
):
    run, job = await _seed(db, user_id, channel_id)
    db.add_all(
        [
            AiVisibilitySource(
                run_id=run.id,
                position=position,
                url=f"https://{label}.example",
                canonical_url=f"https://{label}.example",
                title=label,
                excerpt="Acme Coffee is recommended.",
            )
            for position, label in enumerate(("a", "b"))
        ]
    )
    await db.commit()
    original_status = jobs._status

    async def _status(_db, _run, status):
        if status == "validating":
            raise OSError("database unavailable")
        await original_status(_db, _run, status)

    async def _facts(*_args):
        return {"name": "Acme Coffee"}

    async def _complete(*_args, **_kwargs):
        return "fake:model", research.ResearchPayload(
            answer="Acme Coffee is recommended [S1].",
            claims=[
                research.ResearchClaim(
                    claim="Acme Coffee is recommended",
                    quote="Acme Coffee is recommended",
                    source_ids=["S1"],
                    status="supported",
                )
            ],
            mentioned=True,
            cited=False,
            recommended=True,
            incorrect=False,
        )

    monkeypatch.setattr(jobs, "_status", _status)
    monkeypatch.setattr(jobs, "load_branch_facts", _facts)
    monkeypatch.setattr(jobs.research, "complete_research", _complete)

    result = await jobs.handle_research(job, db)
    await db.refresh(run)
    assert result["status"] == "ambiguous"
    assert run.status == "ambiguous"
    assert run.failure_code == "post_llm_persistence_failed"


@pytest.mark.asyncio
async def test_stale_worker_stops_after_search(
    db, user_id, channel_id, monkeypatch
):
    run, job = await _seed(db, user_id, channel_id)
    run.job_id = job.id
    job.lease_owner = "worker-1"
    job.lease_expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
    await db.commit()
    called = []

    async def _search(*_args):
        job.lease_owner = "worker-2"
        await db.commit()
        return []

    async def _fetch(*_args):
        called.append("fetch")
        return []

    monkeypatch.setattr(jobs.search, "search_public_web", _search)
    monkeypatch.setattr(jobs.sources, "fetch_sources", _fetch)

    result = await jobs.handle_research(job, db)
    assert result["status"] == "cancelled"
    assert called == []


@pytest.mark.asyncio
async def test_job_stops_if_run_disappears_during_search(
    db, user_id, channel_id, monkeypatch
):
    run, job = await _seed(db, user_id, channel_id)
    called = []

    async def _search(_tenant, _query):
        await db.delete(run)
        await db.commit()
        return []

    async def _fetch(*_args):
        called.append("fetch")
        return []

    monkeypatch.setattr(jobs.search, "search_public_web", _search)
    monkeypatch.setattr(jobs.sources, "fetch_sources", _fetch)
    result = await jobs.handle_research(job, db)
    assert result["status"] == "cancelled"
    assert called == []


@pytest.mark.asyncio
async def test_global_search_rate_limit_defers_the_job(
    db, user_id, channel_id, monkeypatch
):
    run, job = await _seed(db, user_id, channel_id)
    job.max_attempts = 3
    await db.commit()

    async def _limited(*_args):
        raise jobs.search.SearchRateLimited("search_rate_limited")

    monkeypatch.setattr(jobs.search, "search_public_web", _limited)
    with pytest.raises(jobs.search.SearchRateLimited, match="search_rate_limited"):
        await jobs.handle_research(job, db)
    await db.refresh(run)
    assert run.status == "searching"
    assert run.completed_at is None


@pytest.mark.asyncio
async def test_tenant_search_rate_limit_is_terminal(
    db, user_id, channel_id, monkeypatch
):
    run, job = await _seed(db, user_id, channel_id)

    async def _limited(*_args):
        raise jobs.search.TenantSearchRateLimited("tenant_search_rate_limited")

    monkeypatch.setattr(jobs.search, "search_public_web", _limited)
    result = await jobs.handle_research(job, db)
    await db.refresh(run)
    assert result["status"] == "failed"
    assert run.failure_code == "TenantSearchRateLimited"


@pytest.mark.asyncio
async def test_job_marks_insufficient_evidence(
    db, user_id, channel_id, monkeypatch
):
    run, job = await _seed(db, user_id, channel_id)

    async def _search(_tenant, _query):
        return [SimpleNamespace(url="https://a.example", title="A", snippet="")]

    async def _fetch(_db, run_id, rows):
        return []

    monkeypatch.setattr(jobs.search, "search_public_web", _search)
    monkeypatch.setattr(jobs.sources, "fetch_sources", _fetch)
    result = await jobs.handle_research(job, db)
    await db.refresh(run)
    assert result["status"] == "insufficient_evidence", run.error
    assert run.status == "insufficient_evidence"

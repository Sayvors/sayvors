"""Durable grounded-research pipeline."""
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
    )
    db.add(job)
    await db.commit()
    return run, job


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
    assert result["status"] == "insufficient_evidence"
    assert run.status == "insufficient_evidence"

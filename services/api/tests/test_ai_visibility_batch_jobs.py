"""Durable business-aware query-set generation handler."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.modules.ai_visibility import batch_jobs, query_sets
from app.modules.ai_visibility.models import (
    AiVisibilityQuestion,
    AiVisibilityQuerySet,
    AiVisibilityRun,
)
from app.modules.ai_visibility.questions import GeneratedQuestion
from app.modules.jobs.models import Job


def _question(text: str, *, language: str = "en", intent: str = "recommendation"):
    return GeneratedQuestion(
        question_text=text,
        language=language,
        intent=intent,
        industry_relevance=90,
        service_relevance=95,
        geographic_context="Makkah",
        business_relevance_score=92,
        priority="P1",
    )


async def _seed_two_question_set(db, user_id, channel_id, monkeypatch):
    query_set = await query_sets.start_query_set(db, user_id, channel_id)
    job = await db.get(Job, query_set.job_id)
    job.status = "running"
    job.lease_owner = "worker-1"
    job.lease_expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
    await db.commit()

    async def _profile(*_args):
        return {
            "name": "Sayvors Company Branch-Makkah",
            "categories": {"primary": "Recruitment office"},
            "description": "Licensed manpower and domestic worker recruitment",
            "services": ["Domestic worker recruitment"],
            "address": "Makkah",
            "locality": "Makkah",
            "website": "https://sayvors.com",
            "public_context": {"website": None, "public_results": [], "uncertainties": []},
        }

    async def _questions(*_args, **_kwargs):
        return [
            _question("Is Sayvors licensed in Makkah?", intent="licensing"),
            _question("هل يقدم Sayvors خدمات استقدام؟", language="ar", intent="services"),
        ]

    monkeypatch.setattr(batch_jobs.profile, "load_business_profile", _profile)
    monkeypatch.setattr(batch_jobs.questions, "generate_questions", _questions)
    await batch_jobs.handle_query_set(job, db)
    return query_set


@pytest.mark.asyncio
async def test_query_set_job_persists_questions_and_starts_first_run(
    db, user_id, channel_id, monkeypatch
):
    query_set = await query_sets.start_query_set(db, user_id, channel_id)
    job = await db.get(Job, query_set.job_id)
    job.status = "running"
    job.lease_owner = "worker-1"
    job.lease_expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
    await db.commit()

    async def _profile(*_args):
        return {
            "name": "Sayvors Company Branch-Makkah",
            "categories": {"primary": "Recruitment office"},
            "description": "Licensed manpower and domestic worker recruitment",
            "services": ["Domestic worker recruitment"],
            "address": "Makkah",
            "locality": "Makkah",
            "website": "https://sayvors.com",
            "public_context": {"website": None, "public_results": [], "uncertainties": []},
        }

    async def _questions(*_args, **_kwargs):
        return [
            _question("Is Sayvors licensed in Makkah?", intent="licensing"),
            _question("هل يقدم Sayvors خدمات استقدام؟", language="ar", intent="services"),
        ]

    monkeypatch.setattr(batch_jobs.profile, "load_business_profile", _profile)
    monkeypatch.setattr(batch_jobs.questions, "generate_questions", _questions)

    result = await batch_jobs.handle_query_set(job, db)
    await db.refresh(query_set)
    assert result["status"] == "running"
    assert query_set.status == "running"
    assert query_set.total_questions == 2
    rows = (
        await db.execute(
            select(AiVisibilityQuestion)
            .where(AiVisibilityQuestion.query_set_id == query_set.id)
            .order_by(AiVisibilityQuestion.position)
        )
    ).scalars().all()
    assert len(rows) == 2
    assert rows[0].run_id
    assert rows[1].run_id is None
    run = await db.get(AiVisibilityRun, rows[0].run_id)
    assert run.query_set_id == query_set.id
    assert run.question_id == rows[0].id
    assert run.status == "queued"


@pytest.mark.asyncio
async def test_query_set_job_marks_empty_generation_failed(
    db, user_id, channel_id, monkeypatch
):
    query_set = await query_sets.start_query_set(db, user_id, channel_id)
    job = await db.get(Job, query_set.job_id)
    job.status = "running"
    job.lease_owner = "worker-1"
    job.lease_expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
    await db.commit()

    async def _profile(*_args):
        return {"name": "Unknown", "categories": {}, "description": ""}

    async def _questions(*_args, **_kwargs):
        return []

    monkeypatch.setattr(batch_jobs.profile, "load_business_profile", _profile)
    monkeypatch.setattr(batch_jobs.questions, "generate_questions", _questions)

    result = await batch_jobs.handle_query_set(job, db)
    await db.refresh(query_set)
    assert result["status"] == "failed"
    assert query_set.status == "failed"
    assert query_set.failure_code == "no_questions_generated"


@pytest.mark.asyncio
async def test_query_set_job_skips_questions_that_already_exist(
    db, user_id, channel_id, monkeypatch
):
    from app.modules.ai_visibility.models import AiVisibilityPrompt
    from app.modules.ai_visibility import service

    query_set = await query_sets.start_query_set(db, user_id, channel_id)
    text = "Is Sayvors licensed in Makkah?"
    db.add(
        AiVisibilityPrompt(
            tenant_id=user_id,
            channel_id=channel_id,
            title="Existing",
            prompt_text=text,
            normalized_prompt_hash=service.prompt_hash(text),
            intent="licensing",
            created_by=user_id,
        )
    )
    await db.commit()
    job = await db.get(Job, query_set.job_id)
    job.status = "running"
    job.lease_owner = "worker-1"
    job.lease_expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
    await db.commit()

    async def _profile(*_args):
        return {"name": "Sayvors", "categories": {"primary": "Recruitment office"}}

    async def _questions(*_args, **_kwargs):
        return [_question(text, intent="licensing")]

    monkeypatch.setattr(batch_jobs.profile, "load_business_profile", _profile)
    monkeypatch.setattr(batch_jobs.questions, "generate_questions", _questions)
    result = await batch_jobs.handle_query_set(job, db)
    await db.refresh(query_set)
    assert result["status"] == "failed"
    assert query_set.failure_code == "no_new_questions"


@pytest.mark.asyncio
async def test_finalizer_advances_one_question_at_a_time(
    db, user_id, channel_id, monkeypatch
):
    query_set = await _seed_two_question_set(db, user_id, channel_id, monkeypatch)
    rows = (
        await db.execute(
            select(AiVisibilityQuestion)
            .where(AiVisibilityQuestion.query_set_id == query_set.id)
            .order_by(AiVisibilityQuestion.position)
        )
    ).scalars().all()
    first_run = await db.get(AiVisibilityRun, rows[0].run_id)
    first_run.status = "completed"
    first_run.completed_at = datetime.now(timezone.utc)
    await db.commit()

    processed = await batch_jobs.finalize_due_query_sets(db)
    await db.refresh(query_set)
    await db.refresh(rows[1])
    assert processed == 1
    assert query_set.status == "running"
    assert rows[0].status == "completed"
    assert rows[1].run_id
    assert rows[1].run_id != rows[0].run_id


@pytest.mark.asyncio
async def test_finalizer_waits_while_current_run_is_active(
    db, user_id, channel_id, monkeypatch
):
    query_set = await _seed_two_question_set(db, user_id, channel_id, monkeypatch)
    rows = (
        await db.execute(
            select(AiVisibilityQuestion)
            .where(AiVisibilityQuestion.query_set_id == query_set.id)
            .order_by(AiVisibilityQuestion.position)
        )
    ).scalars().all()

    await batch_jobs.finalize_due_query_sets(db)
    await db.refresh(rows[1])
    assert rows[1].run_id is None
    assert query_set.status == "running"


@pytest.mark.asyncio
async def test_finalizer_completes_set_after_all_runs_are_terminal(
    db, user_id, channel_id, monkeypatch
):
    query_set = await _seed_two_question_set(db, user_id, channel_id, monkeypatch)
    rows = (
        await db.execute(
            select(AiVisibilityQuestion)
            .where(AiVisibilityQuestion.query_set_id == query_set.id)
            .order_by(AiVisibilityQuestion.position)
        )
    ).scalars().all()
    first = await db.get(AiVisibilityRun, rows[0].run_id)
    first.status = "completed"
    first.completed_at = datetime.now(timezone.utc)
    await db.commit()
    await batch_jobs.finalize_due_query_sets(db)
    second = await db.get(AiVisibilityRun, rows[1].run_id)
    second.status = "insufficient_evidence"
    second.completed_at = datetime.now(timezone.utc)
    await db.commit()

    await batch_jobs.finalize_due_query_sets(db)
    await db.refresh(query_set)
    assert query_set.status == "completed"
    assert query_set.completed_questions == 2
    assert query_set.completed_at is not None


@pytest.mark.asyncio
async def test_finalizer_marks_partial_when_quota_is_exhausted(
    db, user_id, channel_id, monkeypatch
):
    from types import SimpleNamespace

    query_set = await _seed_two_question_set(db, user_id, channel_id, monkeypatch)
    rows = (
        await db.execute(
            select(AiVisibilityQuestion)
            .where(AiVisibilityQuestion.query_set_id == query_set.id)
            .order_by(AiVisibilityQuestion.position)
        )
    ).scalars().all()
    first = await db.get(AiVisibilityRun, rows[0].run_id)
    first.status = "completed"
    first.completed_at = datetime.now(timezone.utc)
    await db.commit()

    async def _entitlements(_tenant, _db):
        return SimpleNamespace(max_quick_research_month=1, max_deep_research_month=None)

    monkeypatch.setattr(batch_jobs.service, "get_entitlements", _entitlements)
    await batch_jobs.finalize_due_query_sets(db)
    await db.refresh(query_set)
    assert query_set.status == "partial"
    assert query_set.failure_code == "research_quota_exhausted"


@pytest.mark.asyncio
async def test_finalizer_creates_adaptive_version_for_grounded_competitor(
    db, user_id, channel_id, monkeypatch
):
    query_set = await _seed_two_question_set(db, user_id, channel_id, monkeypatch)
    rows = (
        await db.execute(
            select(AiVisibilityQuestion)
            .where(AiVisibilityQuestion.query_set_id == query_set.id)
            .order_by(AiVisibilityQuestion.position)
        )
    ).scalars().all()
    first = await db.get(AiVisibilityRun, rows[0].run_id)
    first.status = "completed"
    first.completed_at = datetime.now(timezone.utc)
    first.competitor_mentions = [
        {"name": "Rival Recruitment", "quote": "Rival Recruitment is recommended", "source_ids": ["S1"]}
    ]
    await db.commit()
    await batch_jobs.finalize_due_query_sets(db)
    second = await db.get(AiVisibilityRun, rows[1].run_id)
    second.status = "completed"
    second.completed_at = datetime.now(timezone.utc)
    await db.commit()

    await batch_jobs.finalize_due_query_sets(db)
    versions = (
        await db.execute(
            select(AiVisibilityQuerySet)
            .where(
                AiVisibilityQuerySet.tenant_id == user_id,
                AiVisibilityQuerySet.channel_id == channel_id,
            )
            .order_by(AiVisibilityQuerySet.version)
        )
    ).scalars().all()
    assert len(versions) == 2
    assert versions[0].status == "completed"
    assert versions[1].version == 2
    assert versions[1].parent_query_set_id == versions[0].id
    assert versions[1].generation_meta_json["adaptive_questions"]
    assert any(
        "Rival Recruitment" in row["question_text"]
        for row in versions[1].generation_meta_json["adaptive_questions"]
    )
    followup_job = await db.get(Job, versions[1].job_id)
    followup_job.status = "running"
    followup_job.lease_owner = "worker-2"
    followup_job.lease_expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
    await db.commit()
    await batch_jobs.handle_query_set(followup_job, db)
    followup_rows = (
        await db.execute(
            select(AiVisibilityQuestion)
            .where(AiVisibilityQuestion.query_set_id == versions[1].id)
            .order_by(AiVisibilityQuestion.position)
        )
    ).scalars().all()
    assert followup_rows
    assert followup_rows[0].run_id


@pytest.mark.asyncio
async def test_adaptive_version_does_not_reintroduce_support_chatter(
    db, user_id, channel_id, monkeypatch
):
    query_set = await _seed_two_question_set(db, user_id, channel_id, monkeypatch)
    snapshot = dict(query_set.source_snapshot_json or {})
    snapshot["customer_questions"] = [
        "Update your mobile number please",
        "What is Google Maps?",
    ]
    query_set.source_snapshot_json = snapshot
    await db.commit()
    rows = (
        await db.execute(
            select(AiVisibilityQuestion)
            .where(AiVisibilityQuestion.query_set_id == query_set.id)
            .order_by(AiVisibilityQuestion.position)
        )
    ).scalars().all()
    first = await db.get(AiVisibilityRun, rows[0].run_id)
    first.status = "completed"
    first.completed_at = datetime.now(timezone.utc)
    await db.commit()
    await batch_jobs.finalize_due_query_sets(db)
    second = await db.get(AiVisibilityRun, rows[1].run_id)
    second.status = "completed"
    second.completed_at = datetime.now(timezone.utc)
    await db.commit()

    await batch_jobs.finalize_due_query_sets(db)
    versions = (
        await db.execute(
            select(AiVisibilityQuerySet).where(
                AiVisibilityQuerySet.tenant_id == user_id,
                AiVisibilityQuerySet.channel_id == channel_id,
            )
        )
    ).scalars().all()
    assert len(versions) == 1
    assert versions[0].status == "completed"

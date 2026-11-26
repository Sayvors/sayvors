"""Durable business-aware query-set generation handler."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.modules.ai_visibility import batch_jobs, query_sets
from app.modules.ai_visibility.models import (
    AiVisibilityPrompt,
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

    def _questions(*_args, **_kwargs):
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

    def _questions(*_args, **_kwargs):
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
    child = await db.get(Job, run.job_id)
    assert child.ui_title == "Customer question research"
    assert rows[0].question_text not in child.ui_title


@pytest.mark.asyncio
async def test_query_set_job_uses_real_synchronous_question_generator(
    db, user_id, channel_id, monkeypatch
):
    query_set = await query_sets.start_query_set(db, user_id, channel_id)
    job = await db.get(Job, query_set.job_id)
    job.status = "running"
    job.lease_owner = "worker-real-generator"
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
        }

    monkeypatch.setattr(batch_jobs.profile, "load_business_profile", _profile)
    result = await batch_jobs.handle_query_set(job, db)
    await db.refresh(query_set)
    assert result["status"] == "running"
    assert query_set.total_questions > 0
    assert (
        await db.execute(
            select(AiVisibilityQuestion).where(AiVisibilityQuestion.query_set_id == query_set.id)
        )
    ).scalars().all()


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

    def _questions(*_args, **_kwargs):
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

    def _questions(*_args, **_kwargs):
        return [_question(text, intent="licensing")]

    monkeypatch.setattr(batch_jobs.profile, "load_business_profile", _profile)
    monkeypatch.setattr(batch_jobs.questions, "generate_questions", _questions)
    result = await batch_jobs.handle_query_set(job, db)
    await db.refresh(query_set)
    assert result["status"] == "failed"
    assert query_set.failure_code == "no_new_questions"


@pytest.mark.asyncio
async def test_prompt_limit_failure_rolls_back_partial_questions(
    db, user_id, channel_id, monkeypatch
):
    query_set = await query_sets.start_query_set(db, user_id, channel_id)
    job = await db.get(Job, query_set.job_id)
    job.status = "running"
    job.lease_owner = "worker-1"
    job.lease_expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
    await db.commit()

    async def _profile(*_args):
        return {"name": "Sayvors", "categories": {"primary": "Recruitment office"}}

    def _questions(*_args, **_kwargs):
        return [
            _question("Is Sayvors licensed?", intent="licensing"),
            _question("Does Sayvors recruit workers?", intent="services"),
        ]

    monkeypatch.setattr(batch_jobs.profile, "load_business_profile", _profile)
    monkeypatch.setattr(batch_jobs.questions, "generate_questions", _questions)
    monkeypatch.setattr(batch_jobs.service, "MAX_ACTIVE_PROMPTS_PER_BRANCH", 1)

    result = await batch_jobs.handle_query_set(job, db)
    await db.refresh(query_set)
    assert result["status"] == "failed"
    assert query_set.failure_code == "active_prompt_limit"
    assert (
        await db.execute(
            select(AiVisibilityQuestion).where(AiVisibilityQuestion.query_set_id == query_set.id)
        )
    ).scalars().all() == []
    assert (await db.execute(select(AiVisibilityPrompt))).scalars().all() == []


@pytest.mark.asyncio
async def test_first_child_quota_failure_terminalizes_set(
    db, user_id, channel_id, monkeypatch
):
    query_set = await query_sets.start_query_set(db, user_id, channel_id)
    job = await db.get(Job, query_set.job_id)
    job.status = "running"
    job.lease_owner = "worker-1"
    job.lease_expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
    await db.commit()

    async def _profile(*_args):
        return {"name": "Sayvors", "categories": {"primary": "Recruitment office"}}

    def _questions(*_args, **_kwargs):
        return [_question("Is Sayvors licensed in Makkah?", intent="licensing")]

    async def _quota(*_args, **_kwargs):
        raise batch_jobs.service.ResearchQuotaExceeded("quota")

    monkeypatch.setattr(batch_jobs.profile, "load_business_profile", _profile)
    monkeypatch.setattr(batch_jobs.questions, "generate_questions", _questions)
    monkeypatch.setattr(batch_jobs.service, "create_run_with_quota", _quota)

    result = await batch_jobs.handle_query_set(job, db)
    await db.refresh(query_set)
    assert result["status"] == "partial"
    assert query_set.status == "partial"
    assert query_set.failure_code == "research_quota_exhausted"


@pytest.mark.asyncio
async def test_finalizer_reconciles_dead_parent_job(db, user_id, channel_id):
    query_set = await query_sets.start_query_set(db, user_id, channel_id)
    job = await db.get(Job, query_set.job_id)
    job.status = "dead"
    await db.commit()

    processed = await batch_jobs.finalize_due_query_sets(db)
    await db.refresh(query_set)
    assert processed == 1
    assert query_set.status == "failed"
    assert query_set.failure_code == "generation_job_failed"


@pytest.mark.asyncio
async def test_handler_reentry_does_not_start_a_second_run(
    db, user_id, channel_id, monkeypatch
):
    query_set = await _seed_two_question_set(db, user_id, channel_id, monkeypatch)
    job = await db.get(Job, query_set.job_id)
    job.status = "running"
    job.lease_owner = "worker-2"
    job.lease_expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
    await db.commit()

    await batch_jobs.handle_query_set(job, db)
    runs = (
        await db.execute(
            select(AiVisibilityRun).where(AiVisibilityRun.query_set_id == query_set.id)
        )
    ).scalars().all()
    assert len(runs) == 1


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
    assert versions[1].adaptive_depth == 1
    assert versions[1].parent_query_set_id == versions[0].id
    assert versions[1].classification_json == versions[0].classification_json
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
    assert followup_rows[0].origin == "adaptive"
    assert followup_rows[0].run_id


@pytest.mark.asyncio
async def test_adaptive_cap_uses_cycle_depth_not_branch_version(
    db, user_id, channel_id
):
    from types import SimpleNamespace

    query_set = AiVisibilityQuerySet(
        tenant_id=user_id,
        channel_id=channel_id,
        version=5,
        adaptive_depth=0,
        status="running",
        phase="researching",
        depth="quick",
        classification_json={"industry": "recruitment"},
        source_snapshot_json={"name": "Sayvors", "locality": "Makkah"},
    )
    db.add(query_set)
    await db.flush()
    question = AiVisibilityQuestion(
        query_set_id=query_set.id,
        tenant_id=user_id,
        channel_id=channel_id,
        question_key="q001",
        question_text="Is Sayvors licensed?",
        normalized_question_hash="b" * 64,
        language="en",
        customer_intent="licensing",
        industry_relevance=90,
        service_relevance=95,
        business_relevance_score=92,
        research_priority="P1",
        status="completed",
        position=0,
    )
    db.add(question)
    await db.commit()
    runs = {
        "run-1": SimpleNamespace(
            status="completed",
            competitor_mentions=[
                {"name": "Rival Recruitment", "quote": "Rival is recommended", "source_ids": ["S1"]}
            ],
        )
    }

    followup = await batch_jobs._maybe_create_adaptive_version(
        db, query_set, [question], runs
    )
    assert followup is not None
    assert followup.version == 6
    assert followup.adaptive_depth == 1


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

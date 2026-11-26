"""Background query-set lifecycle and idempotent start behavior."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.modules.ai_visibility import batch_jobs, query_sets
from app.modules.ai_visibility.models import (
    AiVisibilityPrompt,
    AiVisibilityQuestion,
    AiVisibilityQuerySet,
    AiVisibilityRun,
    AiVisibilitySource,
)
from app.modules.jobs.models import Job

@pytest.mark.asyncio
async def test_start_query_set_creates_visible_durable_job(db, user_id, channel_id):
    query_set = await query_sets.start_query_set(
        db, user_id, channel_id, depth="quick"
    )
    assert query_set.status == "generating"
    assert query_set.version == 1
    assert query_set.job_id
    job = await db.get(Job, query_set.job_id)
    assert job.job_type == "ai_visibility.query_set"
    assert job.ui_visible is True
    assert job.ui_title == "Business research"
    assert job.payload == {"query_set_id": query_set.id}


@pytest.mark.asyncio
async def test_start_query_set_is_idempotent_while_active(db, user_id, channel_id):
    first = await query_sets.start_query_set(db, user_id, channel_id)
    second = await query_sets.start_query_set(db, user_id, channel_id)
    assert second.id == first.id
    rows = (await db.execute(select(AiVisibilityQuerySet))).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_start_query_set_increments_version_after_completion(
    db, user_id, channel_id
):
    first = await query_sets.start_query_set(db, user_id, channel_id)
    first.status = "completed"
    await db.commit()
    second = await query_sets.start_query_set(db, user_id, channel_id)
    assert second.version == 2
    assert second.id != first.id


@pytest.mark.asyncio
async def test_start_query_set_rejects_unowned_channel(
    db, user_id, channel_id, other_user_id
):
    with pytest.raises(ValueError, match="channel_not_owned"):
        await query_sets.start_query_set(db, other_user_id, channel_id)


@pytest.mark.asyncio
async def test_latest_query_set_counts_distinct_source_pages(
    db, user_id, channel_id
):
    query_set = AiVisibilityQuerySet(
        tenant_id=user_id,
        channel_id=channel_id,
        version=1,
        status="completed",
        depth="quick",
        source_snapshot_json={"website": "https://sayvors.com"},
    )
    db.add(query_set)
    await db.flush()
    for index in range(2):
        prompt = AiVisibilityPrompt(
            tenant_id=user_id,
            channel_id=channel_id,
            title=f"Question {index}",
            prompt_text=f"Question {index}",
            normalized_prompt_hash=str(index + 10) * 64,
            intent="discovery",
            created_by=user_id,
        )
        db.add(prompt)
        await db.flush()
        question = AiVisibilityQuestion(
            query_set_id=query_set.id,
            tenant_id=user_id,
            channel_id=channel_id,
            question_key=f"q{index + 1:03d}",
            question_text=prompt.prompt_text,
            normalized_question_hash=prompt.normalized_prompt_hash,
            language="en",
            customer_intent="discovery",
            industry_relevance=90,
            service_relevance=95,
            business_relevance_score=92,
            research_priority="P1",
            prompt_id=prompt.id,
            status="completed",
            position=index,
        )
        db.add(question)
        await db.flush()
        run = AiVisibilityRun(
            tenant_id=user_id,
            channel_id=channel_id,
            prompt_id=prompt.id,
            query_set_id=query_set.id,
            question_id=question.id,
            prompt_snapshot=prompt.prompt_text,
            status="completed",
            evidence_coverage={"third_party_source_count": 1, "owned_source_count": 0},
        )
        db.add(run)
        await db.flush()
        question.run_id = run.id
        db.add(
            AiVisibilitySource(
                run_id=run.id,
                position=0,
                url="https://reviews.example/sayvors",
                canonical_url="https://reviews.example/sayvors",
                excerpt="Sayvors review",
            )
        )
    await db.commit()

    latest = await query_sets.latest_query_set(db, user_id, channel_id)
    assert latest["coverage"]["third_party_source_count"] == 1
    assert latest["metrics"]["source_count"] == 1


@pytest.mark.asyncio
async def test_latest_query_set_excludes_failed_and_synthetic_sources(
    db, user_id, channel_id
):
    query_set = AiVisibilityQuerySet(
        tenant_id=user_id,
        channel_id=channel_id,
        version=1,
        status="completed",
        depth="quick",
        source_snapshot_json={"name": "Sayvors", "website": "https://sayvors.com"},
    )
    db.add(query_set)
    await db.flush()
    prompt = AiVisibilityPrompt(
        tenant_id=user_id,
        channel_id=channel_id,
        title="Question",
        prompt_text="Is Sayvors licensed?",
        normalized_prompt_hash="c" * 64,
        intent="licensing",
        created_by=user_id,
    )
    db.add(prompt)
    await db.flush()
    question = AiVisibilityQuestion(
        query_set_id=query_set.id,
        tenant_id=user_id,
        channel_id=channel_id,
        question_key="q001",
        question_text=prompt.prompt_text,
        normalized_question_hash=prompt.normalized_prompt_hash,
        language="en",
        customer_intent="licensing",
        industry_relevance=90,
        service_relevance=95,
        business_relevance_score=92,
        research_priority="P1",
        prompt_id=prompt.id,
        status="completed",
        position=0,
    )
    db.add(question)
    await db.flush()
    run = AiVisibilityRun(
        tenant_id=user_id,
        channel_id=channel_id,
        prompt_id=prompt.id,
        query_set_id=query_set.id,
        question_id=question.id,
        prompt_snapshot=prompt.prompt_text,
        status="completed",
    )
    db.add(run)
    await db.flush()
    question.run_id = run.id
    db.add_all(
        [
            AiVisibilitySource(
                run_id=run.id,
                position=0,
                url="https://failed.example/sayvors",
                canonical_url="https://failed.example/sayvors",
                fetch_error="timeout",
            ),
            AiVisibilitySource(
                run_id=run.id,
                position=1,
                url="about:blank",
                canonical_url="about:blank",
                excerpt="Synthetic",
            ),
        ]
    )
    await db.commit()

    latest = await query_sets.latest_query_set(db, user_id, channel_id)
    assert latest["coverage"]["third_party_source_count"] == 0
    assert latest["metrics"]["source_count"] == 0


@pytest.mark.asyncio
async def test_start_query_set_resumes_pending_questions_from_partial_set(
    db, user_id, channel_id
):
    partial = AiVisibilityQuerySet(
        tenant_id=user_id,
        channel_id=channel_id,
        version=1,
        status="partial",
        phase="complete",
        depth="quick",
        total_questions=2,
        completed_questions=1,
        failure_code="research_quota_exhausted",
        completed_at=datetime.now(timezone.utc),
        classification_json={"industry": "recruitment"},
        source_snapshot_json={"name": "Sayvors", "locality": "Makkah"},
    )
    db.add(partial)
    await db.flush()
    prompts = []
    questions = []
    for index, text in enumerate(("Is Sayvors licensed?", "Does Sayvors recruit domestic workers?")):
        prompt = AiVisibilityPrompt(
            tenant_id=user_id,
            channel_id=channel_id,
            title=f"Question {index}",
            prompt_text=text,
            normalized_prompt_hash=str(index + 1) * 64,
            intent="licensing",
            created_by=user_id,
        )
        db.add(prompt)
        await db.flush()
        question = AiVisibilityQuestion(
            query_set_id=partial.id,
            tenant_id=user_id,
            channel_id=channel_id,
            question_key=f"q{index + 1:03d}",
            question_text=text,
            normalized_question_hash=str(index + 1) * 64,
            language="en",
            customer_intent="licensing",
            industry_relevance=90,
            service_relevance=95,
            geographic_context="Makkah",
            business_relevance_score=92,
            research_priority="P1",
            prompt_id=prompt.id,
            status="completed" if index == 0 else "pending",
            position=index,
        )
        db.add(question)
        prompts.append(prompt)
        questions.append(question)
    await db.flush()
    db.add(
        AiVisibilityRun(
            tenant_id=user_id,
            channel_id=channel_id,
            prompt_id=prompts[0].id,
            query_set_id=partial.id,
            question_id=questions[0].id,
            prompt_snapshot=questions[0].question_text,
            status="completed",
        )
    )
    await db.commit()

    resumed = await query_sets.start_query_set(db, user_id, channel_id)
    assert resumed.version == 2
    assert resumed.parent_query_set_id == partial.id
    rows = (
        await db.execute(
            select(AiVisibilityQuestion)
            .where(AiVisibilityQuestion.query_set_id == resumed.id)
            .order_by(AiVisibilityQuestion.position)
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].carried_from_question_id == questions[1].id
    assert rows[0].prompt_id == questions[1].prompt_id
    assert rows[0].origin == "resume"
    parent = await db.get(Job, resumed.job_id)
    parent.status = "running"
    parent.lease_owner = "worker-resume"
    parent.lease_expires_at = datetime.now(timezone.utc) + timedelta(minutes=5)
    await db.commit()
    await batch_jobs.handle_query_set(parent, db)
    await db.refresh(rows[0])
    assert rows[0].run_id
    resumed_run = await db.get(AiVisibilityRun, rows[0].run_id)
    resumed_run.status = "completed"
    resumed_run.mentioned = True
    await db.commit()
    await batch_jobs.finalize_due_query_sets(db)

    latest = await query_sets.latest_query_set(db, user_id, channel_id)
    assert len(latest["questions"]) == 2
    assert not any(row["status"] == "pending" for row in latest["questions"])
    resumed_payload = next(row for row in latest["questions"] if row["id"] == rows[0].id)
    assert resumed_payload["status"] == "completed"
    assert resumed_payload["carried_from_question_id"] == questions[1].id

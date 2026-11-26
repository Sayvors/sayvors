"""Versioned business-aware query sets and their generated questions."""
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.modules.ai_visibility.models import (
    AiVisibilityPrompt,
    AiVisibilityQuerySet,
    AiVisibilityQuestion,
    AiVisibilityRun,
)


def _set(user_id, channel_id, version=1, status="generating"):
    return AiVisibilityQuerySet(
        tenant_id=user_id,
        channel_id=channel_id,
        version=version,
        status=status,
        depth="quick",
        classification_json={"industry": "recruitment"},
        source_snapshot_json={"website": "https://sayvors.com"},
    )


def _question(query_set, text, key="q1", digest="a" * 64):
    return AiVisibilityQuestion(
        query_set_id=query_set.id,
        tenant_id=query_set.tenant_id,
        channel_id=query_set.channel_id,
        question_key=key,
        question_text=text,
        normalized_question_hash=digest,
        language="en",
        customer_intent="recommendation",
        industry_relevance=90,
        service_relevance=95,
        geographic_context="Makkah",
        business_relevance_score=92,
        research_priority="P1",
        origin="initial",
        position=0,
    )


@pytest.mark.asyncio
async def test_query_set_question_and_run_are_linked(db, user_id, channel_id):
    query_set = _set(user_id, channel_id)
    db.add(query_set)
    await db.flush()
    question = _question(query_set, "Is Sayvors licensed in Makkah?")
    db.add(question)
    prompt = AiVisibilityPrompt(
        tenant_id=user_id,
        channel_id=channel_id,
        title="Generated question",
        prompt_text=question.question_text,
        normalized_prompt_hash=question.normalized_question_hash,
        intent=question.customer_intent,
        created_by=user_id,
    )
    db.add(prompt)
    await db.flush()
    question.prompt_id = prompt.id
    run = AiVisibilityRun(
        tenant_id=user_id,
        channel_id=channel_id,
        prompt_id=prompt.id,
        prompt_snapshot=question.question_text,
        query_set_id=query_set.id,
        question_id=question.id,
        status="queued",
    )
    db.add(run)
    await db.commit()

    assert question.query_set_id == query_set.id
    assert run.query_set_id == query_set.id
    assert run.question_id == question.id


@pytest.mark.asyncio
async def test_query_set_version_is_unique_per_branch(db, user_id, channel_id):
    db.add_all(
        [
            _set(user_id, channel_id, version=1, status="completed"),
            _set(user_id, channel_id, version=1, status="completed"),
        ]
    )
    with pytest.raises(IntegrityError):
        await db.commit()


@pytest.mark.asyncio
async def test_only_one_active_query_set_per_branch(db, user_id, channel_id):
    db.add_all(
        [
            _set(user_id, channel_id, version=1, status="running"),
            _set(user_id, channel_id, version=2, status="generating"),
        ]
    )
    with pytest.raises(IntegrityError):
        await db.commit()


@pytest.mark.asyncio
async def test_non_resume_canonical_question_is_unique_across_versions(
    db, user_id, channel_id
):
    first = _set(user_id, channel_id, version=1, status="completed")
    second = _set(user_id, channel_id, version=2, status="running")
    db.add_all([first, second])
    await db.flush()
    db.add_all(
        [
            _question(first, "Does Sayvors deliver?"),
            _question(second, "Does Sayvors deliver", key="q2"),
        ]
    )
    with pytest.raises(IntegrityError):
        await db.commit()


@pytest.mark.asyncio
async def test_manual_rerun_can_repeat_canonical_question(db, user_id, channel_id):
    first = _set(user_id, channel_id, version=1, status="completed")
    second = _set(user_id, channel_id, version=2, status="running")
    db.add_all([first, second])
    await db.flush()
    original = _question(first, "Does Sayvors deliver?")
    db.add(original)
    await db.flush()
    rerun = _question(second, "Does Sayvors deliver", key="q2")
    rerun.origin = "rerun"
    rerun.carried_from_question_id = original.id
    db.add(rerun)
    await db.commit()
    assert rerun.carried_from_question_id == original.id


@pytest.mark.asyncio
async def test_generated_question_text_can_repeat_in_resumed_version(
    db, user_id, channel_id
):
    first = _set(user_id, channel_id, version=1, status="partial")
    second = _set(user_id, channel_id, version=2, status="running")
    second.parent_query_set_id = first.id
    second.adaptive_depth = 0
    db.add_all([first, second])
    await db.flush()
    first_question = _question(first, "Is Sayvors licensed in Makkah?")
    db.add(first_question)
    await db.flush()
    carried = _question(second, "Is Sayvors licensed in Makkah?", key="q2")
    carried.origin = "resume"
    carried.carried_from_question_id = first_question.id
    db.add(carried)
    await db.commit()

    rows = (await db.execute(select(AiVisibilityQuestion))).scalars().all()
    assert len(rows) == 2
    assert second.adaptive_depth == 0

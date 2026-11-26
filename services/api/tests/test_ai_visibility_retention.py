"""Bounded retention for grounded research evidence."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.modules.ai_visibility import retention
from app.modules.ai_visibility.models import (
    AiVisibilityAttempt,
    AiVisibilityPrompt,
    AiVisibilityQuerySet,
    AiVisibilityQuestion,
    AiVisibilityRun,
)


@pytest.mark.asyncio
async def test_cleanup_deletes_only_old_completed_runs(db, user_id, channel_id):
    prompt = AiVisibilityPrompt(
        tenant_id=user_id,
        channel_id=channel_id,
        title="Coffee",
        prompt_text="Best coffee",
        normalized_prompt_hash="e" * 64,
        intent="discovery",
        created_by=user_id,
    )
    db.add(prompt)
    await db.flush()
    old = AiVisibilityRun(
        tenant_id=user_id,
        channel_id=channel_id,
        prompt_id=prompt.id,
        prompt_snapshot="Best coffee",
        locale="en",
        status="completed",
        completed_at=datetime.now(timezone.utc) - timedelta(days=400),
    )
    active = AiVisibilityRun(
        tenant_id=user_id,
        channel_id=channel_id,
        prompt_id=prompt.id,
        prompt_snapshot="Best coffee",
        locale="en",
        status="queued",
        created_at=datetime.now(timezone.utc) - timedelta(days=400),
    )
    db.add_all([old, active])
    await db.commit()

    deleted = await retention.cleanup_once(db)
    assert deleted == 1
    remaining = (await db.execute(select(AiVisibilityRun))).scalars().all()
    assert [row.id for row in remaining] == [active.id]


@pytest.mark.asyncio
async def test_cleanup_is_bounded(db, user_id, channel_id, monkeypatch):
    monkeypatch.setattr(retention, "CLEANUP_BATCH", 2)
    prompt = AiVisibilityPrompt(
        tenant_id=user_id,
        channel_id=channel_id,
        title="Coffee",
        prompt_text="Best coffee",
        normalized_prompt_hash="f" * 64,
        intent="discovery",
        created_by=user_id,
    )
    db.add(prompt)
    await db.flush()
    db.add_all(
        [
            AiVisibilityRun(
                tenant_id=user_id,
                channel_id=channel_id,
                prompt_id=prompt.id,
                prompt_snapshot="Best coffee",
                locale="en",
                status="completed",
                completed_at=datetime.now(timezone.utc) - timedelta(days=400),
            )
            for _ in range(5)
        ]
    )
    await db.commit()
    assert await retention.cleanup_once(db) == 2


@pytest.mark.asyncio
async def test_cleanup_prunes_old_attempt_ledger_rows(
    db, user_id, channel_id
):
    prompt = AiVisibilityPrompt(
        tenant_id=user_id,
        channel_id=channel_id,
        title="Coffee",
        prompt_text="Best coffee",
        normalized_prompt_hash="2" * 64,
        intent="discovery",
        created_by=user_id,
    )
    db.add(prompt)
    await db.flush()
    old = datetime.now(timezone.utc) - timedelta(days=31)
    db.add_all(
        [
            AiVisibilityAttempt(
                tenant_id=user_id,
                prompt_id=prompt.id,
                run_id="old-attempt",
                attempted_at=old,
            ),
            AiVisibilityAttempt(
                tenant_id=user_id,
                prompt_id=prompt.id,
                run_id="recent-attempt",
                attempted_at=datetime.now(timezone.utc),
            ),
        ]
    )
    await db.commit()

    assert await retention.cleanup_once(db) == 1
    remaining = (
        await db.execute(select(AiVisibilityAttempt))
    ).scalars().all()
    assert [row.run_id for row in remaining] == ["recent-attempt"]


@pytest.mark.asyncio
async def test_old_terminal_failures_are_retained_for_only_thirty_days(
    db, user_id, channel_id
):
    prompt = AiVisibilityPrompt(
        tenant_id=user_id,
        channel_id=channel_id,
        title="Coffee",
        prompt_text="Best coffee",
        normalized_prompt_hash="1" * 64,
        intent="discovery",
        created_by=user_id,
    )
    db.add(prompt)
    await db.flush()
    old = datetime.now(timezone.utc) - timedelta(days=31)
    db.add_all([
        AiVisibilityRun(
            tenant_id=user_id,
            channel_id=channel_id,
            prompt_id=prompt.id,
            prompt_snapshot="Best coffee",
            locale="en",
            status=status,
            completed_at=old,
        )
        for status in ("failed", "insufficient_evidence", "ambiguous")
    ])
    await db.commit()

    assert await retention.cleanup_once(db) == 3


@pytest.mark.asyncio
async def test_cleanup_deletes_old_query_sets_and_cascades_questions(
    db, user_id, channel_id
):
    old = datetime.now(timezone.utc) - timedelta(days=400)
    failed = datetime.now(timezone.utc) - timedelta(days=31)
    completed = AiVisibilityQuerySet(
        tenant_id=user_id,
        channel_id=channel_id,
        version=1,
        status="completed",
        completed_at=old,
    )
    failed_set = AiVisibilityQuerySet(
        tenant_id=user_id,
        channel_id=channel_id,
        version=2,
        status="failed",
        completed_at=failed,
    )
    active = AiVisibilityQuerySet(
        tenant_id=user_id,
        channel_id=channel_id,
        version=3,
        status="running",
        started_at=old,
    )
    db.add_all([completed, failed_set, active])
    await db.flush()
    db.add(
        AiVisibilityQuestion(
            query_set_id=completed.id,
            tenant_id=user_id,
            channel_id=channel_id,
            question_key="q001",
            question_text="Is Sayvors licensed?",
            normalized_question_hash="a" * 64,
            language="en",
            customer_intent="licensing",
            industry_relevance=90,
            service_relevance=95,
            business_relevance_score=92,
            research_priority="P1",
            position=0,
        )
    )
    await db.commit()

    assert await retention.cleanup_once(db) == 2
    remaining = (await db.execute(select(AiVisibilityQuerySet))).scalars().all()
    assert [row.id for row in remaining] == [active.id]
    assert (await db.execute(select(AiVisibilityQuestion))).scalars().all() == []

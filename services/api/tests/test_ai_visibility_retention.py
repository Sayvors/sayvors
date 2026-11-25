"""Bounded retention for grounded research evidence."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.modules.ai_visibility import retention
from app.modules.ai_visibility.models import AiVisibilityPrompt, AiVisibilityRun


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
        status="failed",
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

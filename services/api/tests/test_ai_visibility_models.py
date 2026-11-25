"""Durable AI-visibility prompts, runs, and source snapshots."""
import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.modules.ai_visibility.models import (
    AiVisibilityPrompt,
    AiVisibilityRun,
    AiVisibilitySource,
)


@pytest.mark.asyncio
async def test_prompt_run_and_source_are_tenant_scoped(db, user_id, channel_id):
    prompt = AiVisibilityPrompt(
        tenant_id=user_id,
        channel_id=channel_id,
        title="Coffee",
        prompt_text="Best coffee near Malqa",
        normalized_prompt_hash="a" * 64,
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
    db.add(
        AiVisibilitySource(
            run_id=run.id,
            position=0,
            url="https://example.com",
            canonical_url="https://example.com",
            excerpt="Evidence",
        )
    )
    await db.commit()

    rows = (await db.execute(select(AiVisibilityRun))).scalars().all()
    assert len(rows) == 1
    assert rows[0].tenant_id == user_id
    assert rows[0].prompt_snapshot == "Best coffee near Malqa"


@pytest.mark.asyncio
async def test_only_one_active_run_per_prompt(db, user_id, channel_id):
    prompt = AiVisibilityPrompt(
        tenant_id=user_id,
        channel_id=channel_id,
        title="Coffee",
        prompt_text="Best coffee",
        normalized_prompt_hash="b" * 64,
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
                status="queued",
            ),
            AiVisibilityRun(
                tenant_id=user_id,
                channel_id=channel_id,
                prompt_id=prompt.id,
                prompt_snapshot="Best coffee",
                locale="en",
                status="searching",
            ),
        ]
    )
    with pytest.raises(IntegrityError):
        await db.commit()

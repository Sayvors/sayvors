"""Background query-set lifecycle and idempotent start behavior."""
import pytest
from sqlalchemy import select

from app.modules.ai_visibility import query_sets
from app.modules.ai_visibility.models import AiVisibilityQuerySet
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
    assert job.ui_title
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

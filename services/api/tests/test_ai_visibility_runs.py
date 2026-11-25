"""Durable, idempotent AI-visibility run creation."""
import pytest
from sqlalchemy import select

from app.modules.ai_visibility import service
from app.modules.ai_visibility.models import AiVisibilityPrompt
from app.modules.channels.models import Channel
from app.modules.jobs.models import Job


@pytest.fixture
async def channel_id(db, user_id):
    channel = Channel(
        id="11111111-1111-4111-8111-111111111111",
        user_id=user_id,
        platform="google_reviews",
        platform_user_id="location-1",
        display_name="Acme",
    )
    db.add(channel)
    await db.commit()
    return channel.id


@pytest.fixture(autouse=True)
def _same_site(client):
    client.headers.update({"X-Requested-With": "XMLHttpRequest"})


async def _prompt(db, tenant_id, channel_id):
    row = AiVisibilityPrompt(
        tenant_id=tenant_id,
        channel_id=channel_id,
        title="Coffee",
        prompt_text="Best coffee near Malqa",
        normalized_prompt_hash="c" * 64,
        intent="discovery",
        created_by=tenant_id,
    )
    db.add(row)
    await db.commit()
    return row


@pytest.mark.asyncio
async def test_create_run_is_idempotent(client, db, user_id, channel_id):
    prompt = await _prompt(db, user_id, channel_id)
    body = {"channel_id": channel_id, "prompt_id": prompt.id}

    first = client.post("/api/v1/ai-visibility/runs", json=body)
    second = client.post("/api/v1/ai-visibility/runs", json=body)
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]

    jobs = (
        await db.execute(
            select(Job).where(Job.job_type == "ai_visibility.research")
        )
    ).scalars().all()
    assert len(jobs) == 1
    assert jobs[0].payload["run_id"] == first.json()["id"]


@pytest.mark.asyncio
async def test_inactive_prompt_cannot_run(client, db, user_id, channel_id):
    prompt = await _prompt(db, user_id, channel_id)
    prompt.is_active = False
    await db.commit()
    response = client.post(
        "/api/v1/ai-visibility/runs",
        json={"channel_id": channel_id, "prompt_id": prompt.id},
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_other_tenant_prompt_cannot_run(
    db, user_id, other_user_id, channel_id
):
    prompt = await _prompt(db, other_user_id, channel_id)
    with pytest.raises(service.PromptNotOwned):
        await service.create_run(
            db, user_id, channel_id, prompt.id, locale="en"
        )

"""AI-visibility overview metrics and run history contracts."""
import hashlib
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.modules.ai_visibility.models import (
    AiVisibilityPrompt,
    AiVisibilityRun,
    AiVisibilitySource,
)
from app.modules.channels.models import Channel


@pytest.fixture
async def channel_id(db, user_id):
    channel = Channel(
        id="22222222-2222-4222-8222-222222222222",
        user_id=user_id,
        platform="google_reviews",
        platform_user_id="location-2",
        display_name="Acme",
    )
    db.add(channel)
    await db.commit()
    return channel.id


@pytest.fixture(autouse=True)
def _same_site(client):
    client.headers.update({"X-Requested-With": "XMLHttpRequest"})


async def _completed(db, user_id, channel_id, *, mentioned=True, cited=True):
    prompt = AiVisibilityPrompt(
        tenant_id=user_id,
        channel_id=channel_id,
        title="Coffee",
        prompt_text=f"Prompt {mentioned} {cited}",
        normalized_prompt_hash=hashlib.sha256(
            f"{mentioned}{cited}".encode()
        ).hexdigest(),
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
        status="completed",
        mentioned=mentioned,
        cited=cited,
        recommended=mentioned,
        incorrect=False,
        source_count=2,
        validated_claim_count=1,
        completed_at=datetime.now(timezone.utc),
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
    return run


@pytest.mark.asyncio
async def test_overview_is_null_without_runs(client, user_id, channel_id):
    response = client.get(
        f"/api/v1/ai-visibility/overview?channel_id={channel_id}&days=30"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["completed_runs"] == 0
    assert body["mention_rate"] is None
    assert body["citation_rate"] is None


@pytest.mark.asyncio
async def test_overview_rates_use_completed_runs(
    client, db, user_id, channel_id
):
    await _completed(db, user_id, channel_id, mentioned=True, cited=True)
    await _completed(db, user_id, channel_id, mentioned=False, cited=False)
    body = client.get(
        f"/api/v1/ai-visibility/overview?channel_id={channel_id}&days=30"
    ).json()
    assert body["completed_runs"] == 2
    assert body["mention_rate"] == 50.0
    assert body["citation_rate"] == 50.0
    assert body["recommendation_rate"] == 50.0


@pytest.mark.asyncio
async def test_history_and_detail_are_tenant_scoped(
    client, db, user_id, channel_id
):
    run = await _completed(db, user_id, channel_id)
    listing = client.get(
        f"/api/v1/ai-visibility/runs?channel_id={channel_id}&limit=10&offset=0"
    ).json()
    assert listing["total"] == 1
    assert listing["items"][0]["id"] == run.id

    detail = client.get(f"/api/v1/ai-visibility/runs/{run.id}")
    assert detail.status_code == 200
    assert detail.json()["sources"][0]["excerpt"] == "Evidence"
    assert client.get("/api/v1/ai-visibility/runs/missing").status_code == 404

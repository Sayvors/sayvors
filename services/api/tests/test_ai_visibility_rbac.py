"""AI Visibility honors per-channel team access overrides."""
from uuid import uuid4

import pytest

from app.modules.ai_visibility.models import (
    AiVisibilityPrompt,
    AiVisibilityQuerySet,
    AiVisibilityRun,
)
from app.modules.channels.models import Channel
from app.modules.jobs.models import Job
from tests.test_team_rbac import _auth_as, _seed_member


@pytest.fixture(autouse=True)
def _same_site(client):
    client.headers.update({"X-Requested-With": "XMLHttpRequest"})


@pytest.fixture
async def branch_id(db, user_id):
    channel = Channel(
        id=str(uuid4()),
        user_id=user_id,
        platform="google_reviews",
        platform_user_id="visibility-rbac-location",
        display_name="Visibility Branch",
    )
    db.add(channel)
    await db.commit()
    return channel.id


async def _objects(db, user_id, branch_id):
    prompt = AiVisibilityPrompt(
        tenant_id=user_id,
        channel_id=branch_id,
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
        channel_id=branch_id,
        prompt_id=prompt.id,
        prompt_snapshot=prompt.prompt_text,
        locale="en",
        status="failed",
    )
    db.add(run)
    await db.commit()
    return prompt, run


@pytest.mark.asyncio
async def test_channel_none_blocks_channel_addressed_routes(client, db, user_id, branch_id):
    _member, member_user = await _seed_member(
        db, role_name="Admin", overrides={branch_id: "none"}
    )
    _auth_as(member_user)

    assert client.get(
        f"/api/v1/ai-visibility/prompts?channel_id={branch_id}"
    ).status_code == 404
    assert client.get(
        f"/api/v1/ai-visibility/overview?channel_id={branch_id}&days=30"
    ).status_code == 404
    assert client.get(
        f"/api/v1/ai-visibility/runs?channel_id={branch_id}"
    ).status_code == 404
    assert client.post(
        "/api/v1/ai-visibility/prompts",
        json={
            "channel_id": branch_id,
            "title": "Coffee",
            "prompt_text": "Best coffee near Malqa",
            "intent": "discovery",
        },
    ).status_code == 404


@pytest.mark.asyncio
async def test_channel_none_blocks_object_addressed_routes(client, db, user_id, branch_id):
    prompt, run = await _objects(db, user_id, branch_id)
    _member, member_user = await _seed_member(
        db, role_name="Admin", overrides={branch_id: "none"}
    )
    _auth_as(member_user)

    assert client.patch(
        f"/api/v1/ai-visibility/prompts/{prompt.id}", json={"title": "Stolen"}
    ).status_code == 404
    assert client.delete(
        f"/api/v1/ai-visibility/prompts/{prompt.id}"
    ).status_code == 404
    assert client.get(
        f"/api/v1/ai-visibility/runs/{run.id}"
    ).status_code == 404
    assert client.post(
        f"/api/v1/ai-visibility/runs/{run.id}/retry"
    ).status_code == 404
    assert client.delete(
        f"/api/v1/ai-visibility/runs/{run.id}"
    ).status_code == 404


@pytest.mark.asyncio
async def test_channel_none_hides_background_research_jobs(
    client, db, user_id, branch_id
):
    query_set = AiVisibilityQuerySet(
        id="restricted-query-set",
        tenant_id=user_id,
        channel_id=branch_id,
        version=1,
        status="generating",
        depth="quick",
    )
    db.add(query_set)
    await db.flush()
    db.add(
        Job(
            id="restricted-query-job",
            tenant_id=user_id,
            job_type="ai_visibility.query_set",
            lane="bulk",
            status="queued",
            payload={"query_set_id": query_set.id},
            lane_key="restricted-query",
            ui_visible=True,
            ui_title="Researching restricted branch",
        )
    )
    await db.commit()
    _member, member_user = await _seed_member(
        db, role_name="Admin", overrides={branch_id: "none"}
    )
    _auth_as(member_user)

    response = client.get("/api/v1/jobs/active-ui")
    assert response.status_code == 200
    assert response.json() == []


@pytest.mark.asyncio
async def test_channel_view_allows_reads_but_not_writes(client, db, user_id, branch_id):
    prompt, run = await _objects(db, user_id, branch_id)
    _member, member_user = await _seed_member(
        db, role_name="Admin", overrides={branch_id: "view"}
    )
    _auth_as(member_user)

    assert client.get(
        f"/api/v1/ai-visibility/prompts?channel_id={branch_id}"
    ).status_code == 200
    assert client.get(
        f"/api/v1/ai-visibility/runs/{run.id}"
    ).status_code == 200
    assert client.patch(
        f"/api/v1/ai-visibility/prompts/{prompt.id}", json={"title": "Nope"}
    ).status_code == 404
    assert client.post(
        "/api/v1/ai-visibility/runs",
        json={"channel_id": branch_id, "prompt_id": prompt.id},
    ).status_code == 404

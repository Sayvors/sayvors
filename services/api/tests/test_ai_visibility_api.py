"""Prompt library API behavior and tenant isolation."""
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.modules.ai_visibility.models import AiVisibilityPrompt, AiVisibilityRun
from app.modules.channels.models import Channel


@pytest.fixture(autouse=True)
def _same_site(client):
    client.headers.update({"X-Requested-With": "XMLHttpRequest"})


@pytest_asyncio.fixture
async def channel_id(db, user_id):
    """Use a real UUID-sized channel ID, matching the production column."""
    channel = Channel(
        id=str(uuid4()),
        user_id=user_id,
        platform="google_reviews",
        platform_user_id="prompt-test-location",
        display_name="Prompt Test Burgers",
        status="active",
    )
    db.add(channel)
    await db.commit()
    return channel.id


def _prompt_body(channel_id, *, text="Best coffee near Al Malqa"):
    return {
        "channel_id": channel_id,
        "title": "Coffee",
        "prompt_text": text,
        "intent": "discovery",
    }


@pytest.mark.asyncio
async def test_prompt_crud_and_archive(client, db, user_id, channel_id):
    created = client.post("/api/v1/ai-visibility/prompts", json=_prompt_body(channel_id))
    assert created.status_code == 201, created.text
    prompt_id = created.json()["id"]

    listed = client.get(f"/api/v1/ai-visibility/prompts?channel_id={channel_id}")
    assert listed.status_code == 200
    assert listed.json()["items"][0]["id"] == prompt_id

    patched = client.patch(
        f"/api/v1/ai-visibility/prompts/{prompt_id}",
        json={"title": "Local coffee", "is_active": False},
    )
    assert patched.status_code == 200
    assert patched.json()["title"] == "Local coffee"
    assert patched.json()["is_active"] is False

    active = client.get(f"/api/v1/ai-visibility/prompts?channel_id={channel_id}")
    assert active.json()["items"] == []
    archived = client.get(
        f"/api/v1/ai-visibility/prompts?channel_id={channel_id}&include_archived=true"
    )
    assert [row["id"] for row in archived.json()["items"]] == [prompt_id]

    assert client.delete(f"/api/v1/ai-visibility/prompts/{prompt_id}").status_code == 204
    archived = client.get(
        f"/api/v1/ai-visibility/prompts?channel_id={channel_id}&include_archived=true"
    )
    assert [row["id"] for row in archived.json()["items"]] == [prompt_id]
    assert (await db.get(AiVisibilityPrompt, prompt_id)).is_active is False


@pytest.mark.asyncio
async def test_prompt_with_runs_is_archived_instead_of_deleted(
    client, db, user_id, channel_id
):
    created = client.post("/api/v1/ai-visibility/prompts", json=_prompt_body(channel_id))
    assert created.status_code == 201
    prompt_id = created.json()["id"]
    db.add(AiVisibilityRun(
        tenant_id=user_id,
        channel_id=channel_id,
        prompt_id=prompt_id,
        prompt_snapshot="Best coffee near Al Malqa",
        locale="en",
        status="queued",
    ))
    await db.commit()

    assert client.delete(f"/api/v1/ai-visibility/prompts/{prompt_id}").status_code == 204
    row = await db.get(AiVisibilityPrompt, prompt_id)
    assert row is not None
    assert row.is_active is False


@pytest.mark.asyncio
async def test_prompt_api_rejects_other_tenant_channel(client, db, user_id, other_user_id):
    db.add(Channel(
        id="other-channel",
        user_id=other_user_id,
        platform="google_reviews",
        platform_user_id="other-location",
        display_name="Other",
    ))
    await db.commit()

    response = client.post(
        "/api/v1/ai-visibility/prompts", json=_prompt_body("other-channel")
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "channel_not_found"
    assert (await db.execute(select(AiVisibilityPrompt))).scalars().all() == []


@pytest.mark.asyncio
async def test_prompt_api_cannot_read_or_mutate_other_tenant_prompt(
    client, db, other_user_id
):
    db.add(Channel(
        id="other-channel",
        user_id=other_user_id,
        platform="google_reviews",
        platform_user_id="other-location",
        display_name="Other",
    ))
    prompt = AiVisibilityPrompt(
        tenant_id=other_user_id,
        channel_id="other-channel",
        title="Other",
        prompt_text="Best coffee elsewhere",
        normalized_prompt_hash="d" * 64,
        intent="discovery",
        created_by=other_user_id,
    )
    db.add(prompt)
    await db.commit()

    assert client.get(
        "/api/v1/ai-visibility/prompts?channel_id=other-channel"
    ).status_code == 404
    assert client.patch(
        f"/api/v1/ai-visibility/prompts/{prompt.id}", json={"title": "Stolen"}
    ).status_code == 404
    assert client.delete(
        f"/api/v1/ai-visibility/prompts/{prompt.id}"
    ).status_code == 404
    await db.refresh(prompt)
    assert prompt.title == "Other"


@pytest.mark.asyncio
async def test_prompt_service_rejects_other_tenant_channel(db, user_id, other_user_id):
    from app.modules.ai_visibility import service

    db.add(Channel(
        id="other-channel",
        user_id=other_user_id,
        platform="google_reviews",
        platform_user_id="other-location",
        display_name="Other",
    ))
    await db.commit()

    with pytest.raises(service.OwnedChannelRequired):
        await service.create_prompt(
            db,
            user_id,
            channel_id="other-channel",
            title="X",
            prompt_text="Best coffee",
            intent="discovery",
            created_by=user_id,
        )
    assert (await db.execute(select(AiVisibilityPrompt))).scalars().all() == []


@pytest.mark.asyncio
async def test_duplicate_prompt_uses_normalized_text(client, channel_id):
    first = client.post(
        "/api/v1/ai-visibility/prompts",
        json=_prompt_body(channel_id, text="  Best   COFFEE near Al Malqa  "),
    )
    assert first.status_code == 201
    assert first.json()["prompt_text"] == "Best   COFFEE near Al Malqa"

    duplicate = client.post(
        "/api/v1/ai-visibility/prompts",
        json=_prompt_body(channel_id, text="best coffee near al malqa"),
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == "duplicate_prompt"
    listed = client.get(f"/api/v1/ai-visibility/prompts?channel_id={channel_id}")
    assert len(listed.json()["items"]) == 1


@pytest.mark.asyncio
async def test_patch_cannot_change_prompt_to_a_duplicate(client, channel_id):
    first = client.post(
        "/api/v1/ai-visibility/prompts", json=_prompt_body(channel_id)
    )
    second = client.post(
        "/api/v1/ai-visibility/prompts",
        json=_prompt_body(channel_id, text="Coffee opening hours"),
    )
    assert first.status_code == second.status_code == 201
    first = first.json()
    second = second.json()

    response = client.patch(
        f"/api/v1/ai-visibility/prompts/{first['id']}",
        json={"prompt_text": "  COFFEE   opening hours "},
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "duplicate_prompt"
    listed = client.get(f"/api/v1/ai-visibility/prompts?channel_id={channel_id}")
    rows = {row["id"]: row for row in listed.json()["items"]}
    assert rows[first["id"]]["prompt_text"] == "Best coffee near Al Malqa"
    assert rows[second["id"]]["prompt_text"] == "Coffee opening hours"


@pytest.mark.asyncio
async def test_active_prompt_limit_and_reactivation(client, db, user_id, channel_id):
    from app.modules.ai_visibility import service

    rows = [
        AiVisibilityPrompt(
            tenant_id=user_id,
            channel_id=channel_id,
            title=f"Prompt {index}",
            prompt_text=f"Prompt number {index}",
            normalized_prompt_hash=f"{index:064x}",
            intent="custom",
            created_by=user_id,
        )
        for index in range(service.MAX_ACTIVE_PROMPTS_PER_BRANCH)
    ]
    db.add_all(rows)
    await db.commit()

    blocked = client.post(
        "/api/v1/ai-visibility/prompts",
        json=_prompt_body(channel_id, text="One more prompt"),
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"] == "active_prompt_limit"

    rows[0].is_active = False
    await db.commit()
    assert client.post(
        "/api/v1/ai-visibility/prompts",
        json=_prompt_body(channel_id, text="One more prompt"),
    ).status_code == 201

    reactivated = client.patch(
        f"/api/v1/ai-visibility/prompts/{rows[0].id}", json={"is_active": True}
    )
    assert reactivated.status_code == 409
    assert reactivated.json()["detail"] == "active_prompt_limit"
    await db.refresh(rows[0])
    assert rows[0].is_active is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    [("title", "   "), ("prompt_text", "   "), ("title", None), ("prompt_text", None)],
)
async def test_create_prompt_rejects_blank_or_null_values(
    client, channel_id, field, value
):
    body = _prompt_body(channel_id)
    body[field] = value
    assert client.post("/api/v1/ai-visibility/prompts", json=body).status_code == 422


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("title", "   "),
        ("prompt_text", "   "),
        ("title", None),
        ("prompt_text", None),
        ("intent", None),
        ("is_active", None),
    ],
)
async def test_patch_prompt_rejects_blank_or_null_values(
    client, channel_id, field, value
):
    created_response = client.post(
        "/api/v1/ai-visibility/prompts", json=_prompt_body(channel_id)
    )
    assert created_response.status_code == 201
    created = created_response.json()
    response = client.patch(
        f"/api/v1/ai-visibility/prompts/{created['id']}", json={field: value}
    )
    assert response.status_code == 422
    listed = client.get(f"/api/v1/ai-visibility/prompts?channel_id={channel_id}")
    assert listed.json()["items"][0]["title"] == "Coffee"


@pytest.mark.asyncio
async def test_create_prompt_rate_limit_fails_closed(client, monkeypatch, channel_id):
    from app.config import settings
    from app.modules.ai_visibility import router

    async def _denied(*_args, **_kwargs):
        return False

    monkeypatch.setattr(router, "rate_limit", _denied)
    monkeypatch.setattr(settings, "TESTING", False)
    response = client.post(
        "/api/v1/ai-visibility/prompts", json=_prompt_body(channel_id)
    )
    assert response.status_code == 429
    assert response.json()["detail"] == "too_many_requests"

"""Durable, idempotent AI-visibility run creation."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.modules.ai_visibility import router, service
from app.modules.ai_visibility.models import (
    AiVisibilityAttempt,
    AiVisibilityPrompt,
    AiVisibilityRun,
)
from app.modules.billing.entitlements import EntitlementDenied
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


@pytest.fixture(autouse=True)
def _funded_research(monkeypatch):
    async def _allow(_tenant_id, _feature):
        return None

    async def _balance(_tenant_id):
        return 10_000

    monkeypatch.setattr(router, "check_feature", _allow)
    monkeypatch.setattr(router, "get_balance", _balance)


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
    attempts = (
        await db.execute(
            select(AiVisibilityAttempt).where(
                AiVisibilityAttempt.prompt_id == prompt.id
            )
        )
    ).scalars().all()
    assert len(attempts) == 1
    assert attempts[0].run_id == first.json()["id"]


@pytest.mark.asyncio
async def test_prompt_text_is_immutable_after_research_starts(
    client, db, user_id, channel_id
):
    prompt = await _prompt(db, user_id, channel_id)
    response = client.post(
        "/api/v1/ai-visibility/runs",
        json={"channel_id": channel_id, "prompt_id": prompt.id},
    )
    assert response.status_code == 201

    patched = client.patch(
        f"/api/v1/ai-visibility/prompts/{prompt.id}",
        json={"prompt_text": "A different research question"},
    )
    assert patched.status_code == 409
    assert patched.json()["detail"] == "prompt_text_locked"


@pytest.mark.asyncio
async def test_historical_run_locks_prompt_text_without_a_ledger_row(
    client, db, user_id, channel_id
):
    prompt = await _prompt(db, user_id, channel_id)
    db.add(
        AiVisibilityRun(
            tenant_id=user_id,
            channel_id=channel_id,
            prompt_id=prompt.id,
            prompt_snapshot=prompt.prompt_text,
            locale="en",
            status="completed",
            created_at=datetime.now(timezone.utc) - timedelta(hours=2),
            completed_at=datetime.now(timezone.utc),
        )
    )
    await db.commit()

    response = client.patch(
        f"/api/v1/ai-visibility/prompts/{prompt.id}",
        json={"prompt_text": "A different research question"},
    )
    assert response.status_code == 409
    assert response.json()["detail"] == "prompt_text_locked"


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


@pytest.mark.asyncio
async def test_run_creation_preflights_entitlement(client, db, user_id, channel_id, monkeypatch):
    prompt = await _prompt(db, user_id, channel_id)

    async def _deny(_tenant_id, _feature):
        raise EntitlementDenied("AI replies are disabled", feature="ai_replies")

    monkeypatch.setattr(router, "check_feature", _deny)
    response = client.post(
        "/api/v1/ai-visibility/runs",
        json={"channel_id": channel_id, "prompt_id": prompt.id},
    )
    assert response.status_code == 403
    assert (await db.execute(select(Job))).scalars().all() == []


@pytest.mark.asyncio
async def test_run_creation_preflights_credit_balance(client, db, user_id, channel_id, monkeypatch):
    prompt = await _prompt(db, user_id, channel_id)

    async def _allow(_tenant_id, _feature):
        return None

    async def _empty(_tenant_id):
        return 0

    monkeypatch.setattr(router, "check_feature", _allow)
    monkeypatch.setattr(router, "get_balance", _empty)
    response = client.post(
        "/api/v1/ai-visibility/runs",
        json={"channel_id": channel_id, "prompt_id": prompt.id},
    )
    assert response.status_code == 402
    assert (await db.execute(select(Job))).scalars().all() == []


@pytest.mark.asyncio
async def test_repeated_create_returns_active_run_without_new_spend_preflight(
    client, db, user_id, channel_id, monkeypatch
):
    prompt = await _prompt(db, user_id, channel_id)
    body = {"channel_id": channel_id, "prompt_id": prompt.id}
    first = client.post("/api/v1/ai-visibility/runs", json=body)
    assert first.status_code == 201

    async def _deny(_tenant_id, _feature):
        raise EntitlementDenied("AI replies are disabled", feature="ai_replies")

    monkeypatch.setattr(router, "check_feature", _deny)
    second = client.post("/api/v1/ai-visibility/runs", json=body)
    assert second.status_code == 201
    assert second.json()["id"] == first.json()["id"]


@pytest.mark.asyncio
async def test_retry_active_run_returns_it_without_new_spend_preflight(
    client, db, user_id, channel_id, monkeypatch
):
    prompt = await _prompt(db, user_id, channel_id)
    run = AiVisibilityRun(
        tenant_id=user_id,
        channel_id=channel_id,
        prompt_id=prompt.id,
        prompt_snapshot=prompt.prompt_text,
        locale="en",
        status="queued",
    )
    db.add(run)
    await db.commit()

    async def _deny(_tenant_id, _feature):
        raise EntitlementDenied("AI replies are disabled", feature="ai_replies")

    monkeypatch.setattr(router, "check_feature", _deny)
    response = client.post(f"/api/v1/ai-visibility/runs/{run.id}/retry")
    assert response.status_code == 201
    assert response.json()["id"] == run.id


@pytest.mark.asyncio
async def test_retry_old_run_uses_latest_prompt_completion_for_cooldown(
    client, db, user_id, channel_id
):
    prompt = await _prompt(db, user_id, channel_id)
    old = datetime.now(timezone.utc) - timedelta(minutes=5)
    older_run = AiVisibilityRun(
        tenant_id=user_id,
        channel_id=channel_id,
        prompt_id=prompt.id,
        prompt_snapshot=prompt.prompt_text,
        locale="en",
        status="failed",
        completed_at=old,
    )
    db.add(older_run)
    await db.flush()
    db.add(
        AiVisibilityRun(
            tenant_id=user_id,
            channel_id=channel_id,
            prompt_id=prompt.id,
            prompt_snapshot=prompt.prompt_text,
            locale="en",
            status="failed",
            completed_at=datetime.now(timezone.utc),
        )
    )
    await db.commit()

    response = client.post(f"/api/v1/ai-visibility/runs/{older_run.id}/retry")
    assert response.status_code == 429


@pytest.mark.asyncio
async def test_direct_create_enforces_recent_terminal_cooldown(
    client, db, user_id, channel_id
):
    prompt = await _prompt(db, user_id, channel_id)
    db.add(
        AiVisibilityRun(
            tenant_id=user_id,
            channel_id=channel_id,
            prompt_id=prompt.id,
            prompt_snapshot=prompt.prompt_text,
            locale="en",
            status="failed",
            completed_at=datetime.now(timezone.utc),
        )
    )
    await db.commit()

    response = client.post(
        "/api/v1/ai-visibility/runs",
        json={"channel_id": channel_id, "prompt_id": prompt.id},
    )
    assert response.status_code == 429


@pytest.mark.asyncio
async def test_direct_create_enforces_attempt_limit_even_after_history_delete(
    client, db, user_id, channel_id
):
    prompt = await _prompt(db, user_id, channel_id)
    old = datetime.now(timezone.utc) - timedelta(minutes=5)
    db.add_all(
        [
            AiVisibilityAttempt(
                tenant_id=user_id,
                prompt_id=prompt.id,
                run_id=f"deleted-run-{index}",
                attempted_at=old,
            )
            for index in range(3)
        ]
    )
    db.add(
        AiVisibilityRun(
            tenant_id=user_id,
            channel_id=channel_id,
            prompt_id=prompt.id,
            prompt_snapshot=prompt.prompt_text,
            locale="en",
            status="failed",
            completed_at=old,
        )
    )
    await db.commit()
    run = (await db.execute(select(AiVisibilityRun))).scalars().one()
    assert client.delete(f"/api/v1/ai-visibility/runs/{run.id}").status_code == 204

    response = client.post(
        "/api/v1/ai-visibility/runs",
        json={"channel_id": channel_id, "prompt_id": prompt.id},
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_attempt_limit_counts_the_trailing_hour(
    client, db, user_id, channel_id
):
    prompt = await _prompt(db, user_id, channel_id)
    now = datetime.now(timezone.utc)
    db.add_all(
        [
            AiVisibilityAttempt(
                tenant_id=user_id,
                prompt_id=prompt.id,
                run_id=f"boundary-run-{index}",
                attempted_at=now - timedelta(minutes=minutes),
            )
            for index, minutes in enumerate((59, 30, 2))
        ]
    )
    await db.commit()
    stored = (
        await db.execute(
            select(AiVisibilityAttempt).where(
                AiVisibilityAttempt.prompt_id == prompt.id,
                AiVisibilityAttempt.attempted_at
                >= now - timedelta(minutes=60),
            )
        )
    ).scalars().all()
    assert len(stored) == 3

    response = client.post(
        "/api/v1/ai-visibility/runs",
        json={"channel_id": channel_id, "prompt_id": prompt.id},
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_attempts_older_than_an_hour_do_not_block(
    client, db, user_id, channel_id
):
    prompt = await _prompt(db, user_id, channel_id)
    old = datetime.now(timezone.utc) - timedelta(hours=2)
    db.add_all(
        [
            AiVisibilityAttempt(
                tenant_id=user_id,
                prompt_id=prompt.id,
                run_id=f"old-run-{index}",
                attempted_at=old,
            )
            for index in range(3)
        ]
    )
    await db.commit()

    response = client.post(
        "/api/v1/ai-visibility/runs",
        json={"channel_id": channel_id, "prompt_id": prompt.id},
    )
    assert response.status_code == 201


@pytest.mark.asyncio
async def test_retry_enforces_cooldown(client, db, user_id, channel_id):
    prompt = await _prompt(db, user_id, channel_id)
    run = AiVisibilityRun(
        tenant_id=user_id,
        channel_id=channel_id,
        prompt_id=prompt.id,
        prompt_snapshot=prompt.prompt_text,
        locale="en",
        status="failed",
        completed_at=datetime.now(timezone.utc),
    )
    db.add(run)
    await db.commit()

    response = client.post(f"/api/v1/ai-visibility/runs/{run.id}/retry")
    assert response.status_code == 429


@pytest.mark.asyncio
async def test_retry_attempt_limit(client, db, user_id, channel_id):
    prompt = await _prompt(db, user_id, channel_id)
    old = datetime.now(timezone.utc) - timedelta(minutes=5)
    db.add_all([
        AiVisibilityRun(
            tenant_id=user_id,
            channel_id=channel_id,
            prompt_id=prompt.id,
            prompt_snapshot=prompt.prompt_text,
            locale="en",
            status="failed",
            completed_at=old,
        )
        for _ in range(3)
    ])
    await db.flush()
    runs = (await db.execute(select(AiVisibilityRun))).scalars().all()
    db.add_all([
        AiVisibilityAttempt(
            tenant_id=user_id,
            prompt_id=prompt.id,
            run_id=run.id,
            attempted_at=old,
        )
        for run in runs
    ])
    await db.commit()
    run = runs[0]

    response = client.post(f"/api/v1/ai-visibility/runs/{run.id}/retry")
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_active_run_cannot_be_deleted(client, db, user_id, channel_id):
    prompt = await _prompt(db, user_id, channel_id)
    run = AiVisibilityRun(
        tenant_id=user_id,
        channel_id=channel_id,
        prompt_id=prompt.id,
        prompt_snapshot=prompt.prompt_text,
        locale="en",
        status="searching",
    )
    db.add(run)
    await db.commit()

    response = client.delete(f"/api/v1/ai-visibility/runs/{run.id}")
    assert response.status_code == 409
    assert await db.get(AiVisibilityRun, run.id) is not None

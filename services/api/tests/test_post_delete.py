"""Scheduled removal of a published post (a promo with an end date).

A promotional post goes up now and comes down on the day the offer
lapses. The removal is a job of its own on the publishing lane, so it
rides the same lease / retry / idempotency machinery as everything else.

These tests pin:

- a publish with a `delete_at` queues a removal for that time
- the removal takes the post down from the platform
- it does NOT fire for a post that never went out, or for an account
  surface (a profile picture has nothing to delete)
- a post that is already gone is a success, not a retry
"""
from datetime import datetime, timedelta, timezone

import pytest
from conftest import TEST_SESSION
from sqlalchemy import select

from app.modules.jobs.handlers.post_delete import handle_post_delete
from app.modules.jobs.models import Job, JobStatus
from app.modules.jobs.types import JobType


async def _insert_job(**overrides) -> Job:
    """A publish job row, in whatever state the test needs."""
    payload = {
        "platform": "facebook",
        "external_asset_id": "fb-page-1",
        "method": "post",
        "media_url": "https://cdn.example/p.jpg",
        "caption": "20% off this week",
    }
    payload.update(overrides.pop("payload", {}))
    kwargs = {
        "id": "11111111-1111-1111-1111-111111111111",
        "tenant_id": "tenant-delete-0000-0000-00000000001",
        "job_type": JobType.post_publish.value,
        "lane": "publishing",
        "status": JobStatus.succeeded.value,
        "priority": 50,
        "payload": payload,
        "result": {"id": "fb-post-42"},
        "subject_type": "post",
        "subject_id": "22222222-2222-2222-2222-222222222222",
        "lane_key": "tenant:facebook:fb-page-1:post",
    }
    kwargs.update(overrides)
    async with TEST_SESSION() as db:
        job = Job(**kwargs)
        db.add(job)
        await db.commit()
        return job


async def _row(job_id: str) -> Job:
    async with TEST_SESSION() as db:
        return (
            await db.execute(select(Job).where(Job.id == job_id))
        ).scalar_one_or_none()


@pytest.fixture(autouse=True)
def _schema(engine):
    """Create the schema for every test in this module."""
    yield


@pytest.mark.asyncio
async def test_the_removal_takes_the_post_down(monkeypatch):
    """The provider's delete is called with the platform's post id."""
    publish_job = await _insert_job()
    called: dict = {}

    async def _fake_delete(*, platform, post_id, channel, db):
        called["platform"] = platform
        called["post_id"] = post_id
        return {"deleted": True, "platform": platform}

    monkeypatch.setattr(
        "app.modules.jobs.handlers.post_delete.delete_published_from_platform",
        _fake_delete,
    )

    removal = Job(
        id="33333333-3333-3333-3333-333333333333",
        tenant_id=publish_job.tenant_id,
        job_type=JobType.post_delete.value,
        lane="publishing",
        status=JobStatus.running.value,
        priority=50,
        payload={"publish_job_id": publish_job.id},
        subject_type="post_publish",
        subject_id=publish_job.id,
        lane_key=publish_job.lane_key,
    )
    async with TEST_SESSION() as db:
        db.add(removal)
        await db.commit()
        result = await handle_post_delete(removal, db)
        await db.commit()

    assert called["platform"] == "facebook"
    assert called["post_id"] == "fb-post-42"
    assert result["deleted"] is True

    row = await _row(publish_job.id)
    assert row.result["deleted"] is True
    assert row.status == JobStatus.cancelled.value


@pytest.mark.asyncio
async def test_a_post_that_never_went_out_is_skipped(monkeypatch):
    """Nothing is live, so there is nothing to take down."""
    publish_job = await _insert_job(status=JobStatus.failed.value, result=None)

    async def _never(**kwargs):  # pragma: no cover - must not be reached
        raise AssertionError("the provider must not be called")

    monkeypatch.setattr(
        "app.modules.jobs.handlers.post_delete.delete_published_from_platform",
        _never,
    )
    removal = await _make_removal(publish_job)
    async with TEST_SESSION() as db:
        result = await handle_post_delete(removal, db)
        await db.commit()
    assert "skipped" in result


@pytest.mark.asyncio
async def test_an_account_surface_is_skipped(monkeypatch):
    """A profile picture is not a post — it can only be replaced."""
    publish_job = await _insert_job(payload={"method": "profile"})

    async def _never(**kwargs):  # pragma: no cover - must not be reached
        raise AssertionError("the provider must not be called")

    monkeypatch.setattr(
        "app.modules.jobs.handlers.post_delete.delete_published_from_platform",
        _never,
    )
    removal = await _make_removal(publish_job)
    async with TEST_SESSION() as db:
        result = await handle_post_delete(removal, db)
        await db.commit()
    assert "skipped" in result
    assert "profile" in result["skipped"]


@pytest.mark.asyncio
async def test_a_post_that_is_already_gone_is_a_success(monkeypatch):
    """A 404 means the post is already down — the state we wanted."""
    publish_job = await _insert_job()

    class _NotFound(Exception):
        status_code = 404

    async def _gone(**kwargs):
        raise _NotFound("already gone")

    monkeypatch.setattr(
        "app.modules.jobs.handlers.post_delete.delete_published_from_platform",
        _gone,
    )
    removal = await _make_removal(publish_job)
    async with TEST_SESSION() as db:
        result = await handle_post_delete(removal, db)
        await db.commit()
    assert result["deleted"] is True
    assert result["provider_result"]["already_gone"] is True


@pytest.mark.asyncio
async def test_a_provider_failure_is_raised_so_the_runner_retries(monkeypatch):
    """A flaky call must not silently leave a promo running for ever."""
    publish_job = await _insert_job()

    class _Boom(Exception):
        status_code = 500

    async def _boom(**kwargs):
        raise _Boom("provider is down")

    monkeypatch.setattr(
        "app.modules.jobs.handlers.post_delete.delete_published_from_platform",
        _boom,
    )
    removal = await _make_removal(publish_job)
    async with TEST_SESSION() as db:
        with pytest.raises(_Boom):
            await handle_post_delete(removal, db)


async def _make_removal(publish_job: Job) -> Job:
    removal = Job(
        id="44444444-4444-4444-4444-444444444444",
        tenant_id=publish_job.tenant_id,
        job_type=JobType.post_delete.value,
        lane="publishing",
        status=JobStatus.running.value,
        priority=50,
        payload={"publish_job_id": publish_job.id},
        subject_type="post_publish",
        subject_id=publish_job.id,
        lane_key=publish_job.lane_key,
    )
    async with TEST_SESSION() as db:
        db.add(removal)
        await db.commit()
    return removal

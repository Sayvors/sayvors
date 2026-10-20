"""Publish router: job creation, listing, cancellation and removal.

The posts hub shows every publish job and lets the operator remove a post
from the platform it went out on. These tests pin the behaviour that page
depends on:

- one job per (destination, method), all sharing the caller's batch_id
- the list endpoint echoes the post's own caption + media so the feed can
  render a real card, and never leaks another tenant's jobs
- a job that has not gone out yet is CANCELLED, never "deleted"
- a published job is removed through the provider, best-effort
"""
import uuid

import pytest

from app.modules.jobs.models import Job
from app.modules.jobs.types import JobType


def _job(
    tenant_id: str,
    *,
    status: str = "succeeded",
    platform: str = "instagram",
    method: str = "post",
    asset: str = "1784140001",
    caption: str = "Grand opening",
    media_url: str = "https://cdn.example/post.jpg",
    job_id: str | None = None,
) -> Job:
    return Job(
        id=job_id or str(uuid.uuid4()),
        tenant_id=tenant_id,
        job_type=JobType.post_publish.value,
        lane="publishing",
        status=status,
        priority=50,
        payload={
            "platform": platform,
            "method": method,
            "external_asset_id": asset,
            "caption": caption,
            "media_url": media_url,
            "batch_id": "batch-1",
        },
        result={"id": "post-1"} if status == "succeeded" else None,
        subject_type="post",
        subject_id=str(uuid.uuid4()),
        lane_key=f"{tenant_id}:{platform}:{asset}:{method}",
    )


# ── listing ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_returns_caption_and_media(db, client, user_id):
    """The feed renders a card from the list response — it needs the post's
    own text and media, not just the job id."""
    db.add(_job(user_id, job_id="job-published-0000-0000-000000000001"))
    await db.commit()

    res = client.get("/api/v1/channels/publish")
    assert res.status_code == 200
    rows = res.json()
    assert len(rows) == 1
    row = rows[0]
    assert row["caption"] == "Grand opening"
    assert row["media_url"] == "https://cdn.example/post.jpg"
    assert row["platform"] == "instagram"
    assert row["method"] == "post"
    assert row["status"] == "succeeded"


@pytest.mark.asyncio
async def test_list_never_leaks_other_tenants(db, client, user_id, other_user_id):
    """A job owned by another account must not appear in the feed."""
    mine = _job(user_id, job_id="job-mine-0000-0000-0000-000000000001")
    theirs = _job(other_user_id, job_id="job-theirs-0000-0000-000000000001")
    db.add_all([mine, theirs])
    await db.commit()

    res = client.get("/api/v1/channels/publish")
    assert res.status_code == 200
    ids = {r["job_id"] for r in res.json()}
    assert mine.id in ids
    assert theirs.id not in ids


@pytest.mark.asyncio
async def test_list_filters_by_status(db, client, user_id):
    db.add_all(
        [
            _job(user_id, status="succeeded", job_id="job-ok-0000-0000-0000-00000000001"),
            _job(user_id, status="failed", job_id="job-bad-0000-0000-0000-00000000001"),
        ]
    )
    await db.commit()

    res = client.get("/api/v1/channels/publish?status=failed")
    assert res.status_code == 200
    rows = res.json()
    assert [r["status"] for r in rows] == ["failed"]


# ── creating ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_publish_creates_one_job_per_destination_and_method(db, client, user_id):
    from sqlalchemy import select

    res = client.post(
        "/api/v1/channels/publish",
        json={
            "media_url": "https://cdn.example/post.jpg",
            "media_type": "image",
            "caption": "Hello",
            "description": "Body",
            "batch_id": "batch-9",
            "destinations": [
                {"platform": "instagram", "external_asset_id": "ig-1", "methods": ["post", "story"]},
                {"platform": "facebook", "external_asset_id": "fb-1", "methods": ["post"]},
            ],
        },
    )
    assert res.status_code == 200, res.text
    rows = res.json()
    assert len(rows) == 3
    assert {r["method"] for r in rows} == {"post", "story"}
    assert {r["platform"] for r in rows} == {"instagram", "facebook"}
    assert all(r["batch_id"] == "batch-9" for r in rows)

    # The jobs are persisted for the worker to pick up.
    jobs = (await db.execute(select(Job).where(Job.tenant_id == user_id))).scalars().all()
    assert len(jobs) == 3


def test_publish_rejects_unsupported_platform(client):
    res = client.post(
        "/api/v1/channels/publish",
        json={
            "media_url": "https://cdn.example/post.jpg",
            "destinations": [
                {"platform": "tiktok", "external_asset_id": "tt-1", "methods": ["post"]}
            ],
        },
    )
    assert res.status_code == 422


def test_publish_rejects_past_schedule(client):
    res = client.post(
        "/api/v1/channels/publish",
        json={
            "media_url": "https://cdn.example/post.jpg",
            "scheduled_at": "2000-01-01T00:00:00+00:00",
            "destinations": [
                {"platform": "instagram", "external_asset_id": "ig-1", "methods": ["post"]}
            ],
        },
    )
    assert res.status_code == 422


# ── cancel / delete ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cancel_queued_job(db, client, user_id):
    job = _job(user_id, status="queued", job_id="job-queued-0000-0000-000000000001")
    db.add(job)
    await db.commit()

    res = client.post(f"/api/v1/channels/publish/{job.id}/cancel")
    assert res.status_code == 200
    assert res.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_cancel_refuses_published_job(db, client, user_id):
    """A published post is deleted from the platform, not "cancelled"."""
    job = _job(user_id, status="succeeded", job_id="job-published-0000-0000-000000000001")
    db.add(job)
    await db.commit()

    res = client.post(f"/api/v1/channels/publish/{job.id}/cancel")
    assert res.status_code == 409


@pytest.mark.asyncio
async def test_batch_delete_cancels_a_queued_job(db, client, user_id):
    """Not-yet-published jobs are cancelled by the delete endpoint too."""
    job = _job(user_id, status="queued", job_id="job-queued-0000-0000-000000000001")
    db.add(job)
    await db.commit()

    res = client.post(
        "/api/v1/channels/publish/delete",
        json={"job_ids": [job.id]},
    )
    assert res.status_code == 200, res.text
    rows = res.json()
    assert rows[0]["status"] == "cancelled"
    assert rows[0]["last_error"] == "deleted by user before publish"


@pytest.mark.asyncio
async def test_batch_delete_ignores_other_tenants(db, client, other_user_id):
    theirs = _job(other_user_id, status="queued", job_id="job-theirs-0000-0000-000000000001")
    db.add(theirs)
    await db.commit()

    res = client.post(
        "/api/v1/channels/publish/delete",
        json={"job_ids": [theirs.id]},
    )
    # Nothing of the caller's was touched, so the request is refused.
    assert res.status_code == 404

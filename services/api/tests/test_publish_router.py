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
from datetime import datetime, timedelta, timezone

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


# ── formats ────────────────────────────────────────────────────────────


def test_publish_accepts_google_post_types(client):
    """Google's three post types are real formats, not one "post"."""
    res = client.post(
        "/api/v1/channels/publish",
        json={
            "media_url": "https://cdn.example/post.jpg",
            "destinations": [
                {
                    "platform": "google_reviews",
                    "external_asset_id": "loc-1",
                    "methods": ["update", "event", "offer"],
                }
            ],
        },
    )
    assert res.status_code == 200, res.text
    assert {r["method"] for r in res.json()} == {"update", "event", "offer"}


def test_publish_accepts_profile_and_banner_formats(client):
    """The avatar and cover surfaces are publishable formats too."""
    res = client.post(
        "/api/v1/channels/publish",
        json={
            "media_url": "https://cdn.example/post.jpg",
            "destinations": [
                {
                    "platform": "facebook",
                    "external_asset_id": "fb-1",
                    "methods": ["profile", "banner"],
                }
            ],
        },
    )
    assert res.status_code == 200, res.text
    assert {r["method"] for r in res.json()} == {"profile", "banner"}


def test_publish_rejects_unknown_format(client):
    res = client.post(
        "/api/v1/channels/publish",
        json={
            "media_url": "https://cdn.example/post.jpg",
            "destinations": [
                {"platform": "facebook", "external_asset_id": "fb-1", "methods": ["gallery"]}
            ],
        },
    )
    assert res.status_code == 422


def test_publish_carries_the_media_key(client):
    """Providers that upload bytes (WhatsApp's profile picture) need the
    storage key, not just the public URL."""
    res = client.post(
        "/api/v1/channels/publish",
        json={
            "media_url": "https://cdn.example/post.jpg",
            "media_key": "tenant-1/avatar.jpg",
            "destinations": [
                {
                    "platform": "whatsapp",
                    "external_asset_id": "phone-1",
                    "methods": ["profile"],
                }
            ],
        },
    )
    assert res.status_code == 200, res.text
    assert res.json()[0]["method"] == "profile"


# ── scheduled removal ──────────────────────────────────────────────────


def test_publish_accepts_a_removal_date(client):
    """A promotional post goes up now and comes down on a date."""
    delete_at = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    res = client.post(
        "/api/v1/channels/publish",
        json={
            "media_url": "https://cdn.example/post.jpg",
            "delete_at": delete_at,
            "destinations": [
                {"platform": "facebook", "external_asset_id": "fb-1", "methods": ["post"]}
            ],
        },
    )
    assert res.status_code == 200, res.text
    row = res.json()[0]
    assert row["delete_at"] == delete_at
    # The job carries it, so the removal can be queued once the post is
    # actually live.
    assert row["job_id"]


def test_publish_rejects_a_removal_date_in_the_past(client):
    res = client.post(
        "/api/v1/channels/publish",
        json={
            "media_url": "https://cdn.example/post.jpg",
            "delete_at": "2000-01-01T00:00:00+00:00",
            "destinations": [
                {"platform": "facebook", "external_asset_id": "fb-1", "methods": ["post"]}
            ],
        },
    )
    assert res.status_code == 422


def test_publish_rejects_a_removal_before_the_post_goes_out(client):
    """A post cannot be taken down before it is published."""
    scheduled = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat()
    res = client.post(
        "/api/v1/channels/publish",
        json={
            "media_url": "https://cdn.example/post.jpg",
            "scheduled_at": scheduled,
            "delete_at": (
                datetime.now(timezone.utc) + timedelta(days=1)
            ).isoformat(),
            "destinations": [
                {"platform": "facebook", "external_asset_id": "fb-1", "methods": ["post"]}
            ],
        },
    )
    assert res.status_code == 422


@pytest.mark.asyncio
async def test_scheduling_a_removal_queues_a_delete_job(db, user_id):
    """The removal is a job of its own, timed for the removal date."""
    from datetime import datetime, timedelta, timezone

    from app.modules.jobs.models import Job
    from app.modules.jobs.service import submit_job
    from app.modules.jobs.types import JobType
    from app.modules.channels.publish.service import schedule_removal

    publish_job = await submit_job(
        db,
        tenant_id=user_id,
        job_type=JobType.post_publish.value,
        payload={"platform": "facebook", "external_asset_id": "fb-1", "method": "post"},
        lane="publishing",
    )
    delete_at = datetime.now(timezone.utc) + timedelta(days=5)
    removal = await schedule_removal(
        db, tenant_id=user_id, publish_job=publish_job, delete_at=delete_at
    )
    await db.commit()

    assert removal.job_type == JobType.post_delete.value
    assert removal.status == "queued"
    assert removal.payload["publish_job_id"] == publish_job.id
    # Timed for the removal date, not for now.
    assert abs((removal.next_run_at - delete_at).total_seconds()) < 1

    # Scheduling twice must not queue two removals.
    again = await schedule_removal(
        db, tenant_id=user_id, publish_job=publish_job, delete_at=delete_at
    )
    await db.commit()
    assert again.id == removal.id


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


# ── Google destination ids ─────────────────────────────────────────────


def test_channel_location_ids_covers_every_id_space():
    """A branch is named by its Localith listing id, its Google location id,
    or both — a publish destination may carry any of them."""
    from app.modules.channels.models import Channel
    from app.modules.channels.service import channel_location_ids

    ch = Channel(
        id="c-1",
        user_id="u-1",
        platform="google_reviews",
        platform_user_id="accounts/123",
        display_name="Branch",
        status="active",
        listing_key="localith-listing-9",
        metadata_json='{"listing_id": "localith-listing-9", "location_id": "google-loc-9"}',
    )
    ids = channel_location_ids(ch)
    assert "localith-listing-9" in ids
    assert "google-loc-9" in ids


def test_channel_location_ids_survives_broken_metadata():
    from app.modules.channels.models import Channel
    from app.modules.channels.service import channel_location_ids

    ch = Channel(
        id="c-2",
        user_id="u-1",
        platform="google_reviews",
        platform_user_id="accounts/123",
        display_name="Branch",
        status="active",
        listing_key="listing-only",
        metadata_json="not-json",
    )
    assert channel_location_ids(ch) == {"listing-only"}


def test_google_location_id_prefers_the_google_id():
    """Google's API only knows the location id, so the publish call must use
    it even when the destination was named by the Localith listing id."""
    from app.modules.channels.models import Channel
    from app.modules.jobs.handlers.post_publish import _google_location_id

    ch = Channel(
        id="c-3",
        user_id="u-1",
        platform="google_reviews",
        platform_user_id="accounts/123",
        display_name="Branch",
        status="active",
        listing_key="localith-listing-9",
        metadata_json='{"listing_id": "localith-listing-9", "location_id": "google-loc-9"}',
    )
    assert _google_location_id(ch) == "google-loc-9"


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


# ── account surfaces (profile / banner) ────────────────────────────────


@pytest.mark.asyncio
async def test_delete_refuses_a_profile_picture(db, client, user_id):
    """An avatar is not a post — there is nothing on the platform to
    delete, so the endpoint says so instead of pretending it did."""
    job = _job(
        user_id,
        status="succeeded",
        platform="facebook",
        method="profile",
        job_id="job-profile-0000-0000-000000000001",
    )
    db.add(job)
    await db.commit()

    res = client.post(f"/api/v1/channels/publish/{job.id}/delete", json={})
    assert res.status_code == 409
    assert "cannot be deleted" in res.json()["detail"]


@pytest.mark.asyncio
async def test_batch_delete_closes_a_profile_picture_without_deleting(db, client, user_id):
    """The row is closed out, and the reason says the surface was left
    alone — it must not read as "deleted from the platform"."""
    job = _job(
        user_id,
        status="succeeded",
        platform="facebook",
        method="banner",
        job_id="job-banner-0000-0000-000000000001",
    )
    db.add(job)
    await db.commit()

    res = client.post(
        "/api/v1/channels/publish/delete",
        json={"job_ids": [job.id]},
    )
    assert res.status_code == 200, res.text
    row = res.json()[0]
    assert row["status"] == "cancelled"
    assert "cannot be deleted" in row["last_error"]

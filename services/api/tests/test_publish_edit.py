"""Editing and checking publish jobs: what the feed's details view can change.

A job that has not reached the platform changes freely. A published Google post
changes on Google through its own API, and a Google refusal leaves the job as it
was. Anything that cannot change on the platform is refused with the reason.
"""

import json
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.modules.channels.google_reviews import GoogleReviewsError
from app.modules.channels.models import Channel
from app.modules.channels.service import encrypt_token
from app.modules.jobs.models import Job
from app.modules.jobs.types import JobType

LOCATION = "181507565693476724"
POST_NAME = f"accounts/1/locations/{LOCATION}/localPosts/77"


async def _reload(db, job_id: str) -> Job:
    """The job as it is now in the database.

    The test session keeps the objects it loaded (expire_on_commit is off), so
    a plain select would return the values the test itself wrote.
    """
    return (
        await db.execute(
            select(Job).where(Job.id == job_id).execution_options(populate_existing=True)
        )
    ).scalar_one()


def _as_utc(value: datetime) -> datetime:
    """The database returns next_run_at as naive UTC."""
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _future(days: float) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def _job(
    tenant_id: str,
    *,
    status: str = "succeeded",
    platform: str = "google_reviews",
    method: str = "update",
    caption: str = "Hello",
    result: dict | None = None,
) -> Job:
    if result is None and status == "succeeded":
        result = {"id": POST_NAME, "name": POST_NAME, "state": "LIVE"}
    return Job(
        id=str(uuid.uuid4()),
        tenant_id=tenant_id,
        job_type=JobType.post_publish.value,
        lane="publishing",
        status=status,
        priority=50,
        payload={
            "platform": platform,
            "method": method,
            "external_asset_id": LOCATION,
            "caption": caption,
            "description": "",
            "media_url": "https://cdn.example/p.jpg",
            "batch_id": "batch-1",
        },
        result=result,
        subject_type="post",
        subject_id=str(uuid.uuid4()),
        lane_key=f"{tenant_id}:{platform}:{LOCATION}:{method}",
    )


async def _google_channel(db, user_id: str) -> None:
    db.add(
        Channel(
            id=f"ch-edit-{user_id[-12:]}",
            user_id=user_id,
            platform="google_reviews",
            platform_user_id="1",
            display_name="Test branch",
            status="active",
            listing_key=LOCATION,
            access_token=encrypt_token("at"),
            refresh_token=encrypt_token("rt"),
            metadata_json=json.dumps({"location_id": LOCATION}),
        )
    )
    await db.commit()


def _patch_publisher(monkeypatch, *, update_error=None, get_error=None) -> dict:
    """Replace the Google publisher with a recorder for the request sequence."""
    seen: dict = {"updates": [], "gets": 0}

    class _Fake:
        def __init__(self, token, refresh=None):
            pass

        def set_known_expiry(self, expires_at):
            pass

        def set_token_persister(self, persister):
            pass

        async def update_post(self, post_name, fields):
            seen["updates"].append((post_name, fields))
            if update_error is not None:
                raise update_error
            return {"name": post_name, "state": "LIVE", "summary": fields.get("summary")}

        async def get_post(self, post_name):
            seen["gets"] += 1
            if get_error is not None:
                raise get_error
            return {"name": post_name, "state": "SCHEDULED", "mediaCount": 1}

        async def close(self):
            pass

    monkeypatch.setattr(
        "app.modules.channels.publish.router.GoogleBusinessPublisher", _Fake
    )
    return seen


# ── queued: every field changes, nothing is sent to a platform ──────────


@pytest.mark.asyncio
async def test_a_queued_job_takes_every_change(db, client, user_id):
    job = _job(user_id, status="queued", result=None)
    db.add(job)
    await db.commit()

    res = client.patch(
        f"/api/v1/channels/publish/{job.id}",
        json={"caption": "Edited", "scheduled_at": _future(2)},
    )
    assert res.status_code == 200, res.text
    row = await _reload(db, job.id)
    assert row.payload["caption"] == "Edited"
    assert row.payload["scheduled_at"]


@pytest.mark.asyncio
async def test_a_past_schedule_is_refused(db, client, user_id):
    job = _job(user_id, status="queued", result=None)
    db.add(job)
    await db.commit()

    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    res = client.patch(f"/api/v1/channels/publish/{job.id}", json={"scheduled_at": past})
    assert res.status_code == 422
    assert "future" in res.json()["detail"]


# ── published Google post: the change happens on Google ─────────────────


@pytest.mark.asyncio
async def test_a_published_google_post_is_changed_on_google(db, client, user_id, monkeypatch):
    await _google_channel(db, user_id)
    job = _job(user_id)
    db.add(job)
    await db.commit()
    seen = _patch_publisher(monkeypatch)

    res = client.patch(
        f"/api/v1/channels/publish/{job.id}",
        json={
            "caption": "Edited caption",
            "cta_type": "shop",
            "cta_url": "https://shop.example",
        },
    )
    assert res.status_code == 200, res.text
    name, fields = seen["updates"][0]
    assert name == POST_NAME
    assert fields["summary"] == "Edited caption"
    assert fields["callToAction"] == {"actionType": "SHOP", "url": "https://shop.example"}
    row = await _reload(db, job.id)
    assert row.payload["caption"] == "Edited caption"
    assert row.payload["cta_type"] == "shop"
    assert row.result["state"] == "LIVE"


@pytest.mark.asyncio
async def test_clearing_the_caption_clears_the_text_on_google(db, client, user_id, monkeypatch):
    await _google_channel(db, user_id)
    job = _job(user_id)
    db.add(job)
    await db.commit()
    seen = _patch_publisher(monkeypatch)

    res = client.patch(f"/api/v1/channels/publish/{job.id}", json={"caption": None})
    assert res.status_code == 200, res.text
    _, fields = seen["updates"][0]
    assert "summary" in fields and fields["summary"] is None


@pytest.mark.asyncio
async def test_a_google_refusal_leaves_the_job_unchanged(db, client, user_id, monkeypatch):
    await _google_channel(db, user_id)
    job = _job(user_id, caption="Original")
    db.add(job)
    await db.commit()
    _patch_publisher(monkeypatch, update_error=GoogleReviewsError("Unknown name", 400))

    res = client.patch(f"/api/v1/channels/publish/{job.id}", json={"caption": "Will fail"})
    assert res.status_code == 502
    row = await _reload(db, job.id)
    assert row.payload["caption"] == "Original"


@pytest.mark.asyncio
async def test_a_published_facebook_post_text_cannot_be_edited_here(db, client, user_id):
    job = _job(user_id, platform="facebook", method="post")
    db.add(job)
    await db.commit()

    res = client.patch(f"/api/v1/channels/publish/{job.id}", json={"caption": "x"})
    assert res.status_code == 409


@pytest.mark.asyncio
async def test_a_failed_job_cannot_be_edited(db, client, user_id):
    job = _job(user_id, status="failed", result=None)
    db.add(job)
    await db.commit()

    res = client.patch(f"/api/v1/channels/publish/{job.id}", json={"caption": "x"})
    assert res.status_code == 409


# ── removal date: Sayvors' own removal job moves, is set or is cancelled ─


@pytest.mark.asyncio
async def test_a_removal_date_can_be_set_moved_and_cancelled(db, client, user_id):
    job = _job(user_id, platform="facebook", method="post")
    db.add(job)
    await db.commit()

    res = client.patch(f"/api/v1/channels/publish/{job.id}", json={"delete_at": _future(3)})
    assert res.status_code == 200, res.text
    removal = (
        await db.execute(
            select(Job)
            .where(Job.idempotency_key == f"post-delete:{job.id}")
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert removal.job_type == JobType.post_delete.value
    assert _as_utc(removal.next_run_at) > datetime.now(timezone.utc) + timedelta(days=2)

    res = client.patch(f"/api/v1/channels/publish/{job.id}", json={"delete_at": _future(5)})
    assert res.status_code == 200, res.text
    await db.refresh(removal)
    assert _as_utc(removal.next_run_at) > datetime.now(timezone.utc) + timedelta(days=4)

    res = client.patch(f"/api/v1/channels/publish/{job.id}", json={"delete_at": None})
    assert res.status_code == 200, res.text
    await db.refresh(removal)
    assert removal.status == "cancelled"


@pytest.mark.asyncio
async def test_a_live_post_with_a_past_schedule_can_still_get_a_removal_date(
    db, client, user_id
):
    """Its scheduled time has already passed, so the post is out: a removal
    after now is valid and must not be compared against the old schedule."""
    past = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    job = _job(user_id, platform="facebook", method="post")
    job.payload = {**job.payload, "scheduled_at": past}
    db.add(job)
    await db.commit()

    res = client.patch(f"/api/v1/channels/publish/{job.id}", json={"delete_at": _future(3)})
    assert res.status_code == 200, res.text
    removal = (
        await db.execute(
            select(Job)
            .where(Job.idempotency_key == f"post-delete:{job.id}")
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    assert _as_utc(removal.next_run_at) > datetime.now(timezone.utc) + timedelta(days=2)


@pytest.mark.asyncio
async def test_a_published_post_cannot_be_scheduled_again(db, client, user_id):
    job = _job(user_id, platform="facebook", method="post")
    db.add(job)
    await db.commit()

    res = client.patch(
        f"/api/v1/channels/publish/{job.id}", json={"scheduled_at": _future(2)}
    )
    assert res.status_code == 409
    assert "scheduled again" in res.json()["detail"]


# ── refresh: what Google reports now ────────────────────────────────────


@pytest.mark.asyncio
async def test_refresh_records_the_state_google_reports(db, client, user_id, monkeypatch):
    await _google_channel(db, user_id)
    job = _job(user_id)
    db.add(job)
    await db.commit()
    _patch_publisher(monkeypatch)

    res = client.post(f"/api/v1/channels/publish/{job.id}/refresh")
    assert res.status_code == 200, res.text
    assert res.json()["result"]["state"] == "SCHEDULED"


@pytest.mark.asyncio
async def test_refresh_records_a_post_google_no_longer_has_as_gone(db, client, user_id, monkeypatch):
    await _google_channel(db, user_id)
    job = _job(user_id)
    db.add(job)
    await db.commit()
    _patch_publisher(monkeypatch, get_error=GoogleReviewsError("not found", 404))

    res = client.post(f"/api/v1/channels/publish/{job.id}/refresh")
    assert res.status_code == 200, res.text
    assert res.json()["result"]["state"] == "GONE"


# ── create: a Google post needs text or an image ────────────────────────


def test_a_google_post_with_no_text_and_no_image_is_refused(client):
    res = client.post(
        "/api/v1/channels/publish",
        json={
            "destinations": [
                {"platform": "google_reviews", "external_asset_id": "loc-1", "methods": ["update"]},
            ],
        },
    )
    assert res.status_code == 422
    assert "needs a caption" in res.json()["detail"]

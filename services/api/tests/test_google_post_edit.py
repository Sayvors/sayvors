"""Editing / removing posts that already live on Google.

Imported Google posts are mirrors of a remote localPost. These tests pin:
  * an edit is pushed to Google and mirrored locally
  * a post without a google_post_id is refused
  * a Google failure surfaces as a 502, not a silent local-only change
  * remove deletes on Google then drops the local row
"""
from datetime import datetime, timezone

import pytest

from app.modules.channels.service import encrypt_token
from app.modules.posts.models import LocationPost


async def _seed_channel(db, user_id, channel_id, listing_id="demo-loc-456"):
    """The fixture channel has no tokens by default; a real connect stores them."""
    channel = await db.get(__import__(
        "app.modules.channels.models", fromlist=["Channel"]
    ).Channel, channel_id)
    if channel is None:
        return
    channel.access_token = encrypt_token("test-token")
    channel.refresh_token = encrypt_token("test-refresh")
    channel.status = "active"
    db.add(channel)
    await db.commit()


def _post(**over):
    data = dict(
        id="gp-1",
        user_id="test-user-0000-0000-0000-000000000001",
        listing_id="demo-loc-456",
        location_name="Test Burgers",
        business_name="Test Burgers",
        title="Hello",
        description="Original text",
        post_type="update",
        status="published",
        google_post_id="accounts/a/locations/l/localPosts/p1",
    )
    data.update(over)
    return LocationPost(**data)


@pytest.mark.asyncio
async def test_update_pushes_to_google_and_mirrors(client, db, user_id, channel_id, monkeypatch):
    await _seed_channel(db, user_id, channel_id)
    db.add(_post())
    await db.commit()

    calls = {}

    async def _update(self, post_name, fields):
        calls["post_name"] = post_name
        calls["fields"] = fields
        return {"name": post_name, "state": "PUBLISHED"}

    monkeypatch.setattr(
        "app.modules.channels.meta.providers.google_publish.GoogleBusinessPublisher.update_post",
        _update,
    )

    r = client.patch(
        "/api/v1/posts/gp-1/google",
        json={"description": "Updated text", "cta_type": "learn_more", "cta_url": "https://x.dev"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["google_published"] is True
    assert body["post"]["description"] == "Updated text"

    assert calls["post_name"] == "accounts/a/locations/l/localPosts/p1"
    assert calls["fields"]["summary"] == "Hello\n\nUpdated text"
    assert calls["fields"]["callToAction"]["actionType"] == "LEARN_MORE"

    row = await db.get(LocationPost, "gp-1")
    assert row.description == "Updated text"
    assert row.cta_type == "learn_more"


@pytest.mark.asyncio
async def test_update_refuses_post_not_on_google(client, db, user_id, channel_id):
    db.add(_post(google_post_id=None))
    await db.commit()
    r = client.patch("/api/v1/posts/gp-1/google", json={"description": "x"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_update_google_failure_is_502(client, db, user_id, channel_id, monkeypatch):
    await _seed_channel(db, user_id, channel_id)
    db.add(_post())
    await db.commit()

    async def _boom(self, post_name, fields):
        raise RuntimeError("Google refused")

    monkeypatch.setattr(
        "app.modules.channels.meta.providers.google_publish.GoogleBusinessPublisher.update_post",
        _boom,
    )
    r = client.patch("/api/v1/posts/gp-1/google", json={"description": "x"})
    assert r.status_code == 502
    # Local row must not change when Google refused.
    row = await db.get(LocationPost, "gp-1")
    assert row.description == "Original text"


@pytest.mark.asyncio
async def test_delete_removes_on_google_and_drops_row(client, db, user_id, channel_id, monkeypatch):
    await _seed_channel(db, user_id, channel_id)
    db.add(_post())
    await db.commit()

    calls = {}

    async def _delete(self, token, post_id):
        calls["post_id"] = post_id
        return {"deleted": True}

    monkeypatch.setattr(
        "app.modules.channels.meta.providers.google_publish.GoogleBusinessPublisher.delete_post",
        _delete,
    )

    r = client.delete("/api/v1/posts/gp-1/google")
    assert r.status_code == 204
    assert calls["post_id"] == "accounts/a/locations/l/localPosts/p1"
    assert await db.get(LocationPost, "gp-1") is None


@pytest.mark.asyncio
async def test_event_window_is_pushed_for_event_posts(client, db, user_id, channel_id, monkeypatch):
    await _seed_channel(db, user_id, channel_id)
    db.add(_post(post_type="event", start_date=datetime(2026, 12, 1, 10, 0, tzinfo=timezone.utc)))
    await db.commit()

    calls = {}

    async def _update(self, post_name, fields):
        calls["fields"] = fields
        return {"name": post_name}

    monkeypatch.setattr(
        "app.modules.channels.meta.providers.google_publish.GoogleBusinessPublisher.update_post",
        _update,
    )

    r = client.patch(
        "/api/v1/posts/gp-1/google",
        json={"end_date": "2026-12-02T10:00:00Z"},
    )
    assert r.status_code == 200, r.text
    assert "event" in calls["fields"]

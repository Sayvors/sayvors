"""Location posts CRUD + publish + sync (Google push is monkeypatched)."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.modules.localith.models import LocalithConnection
from app.modules.posts import service as posts


async def _connection(db, user_id):
    db.add(LocalithConnection(
        id="conn-post-1", user_id=user_id, listing_id="loc-1",
        listing_name="Test Place", listing_google_id="g1",
    ))
    await db.commit()


def _draft(listing_id="loc-1", **over):
    data = {
        "listing_id": listing_id, "location_name": "Test Place",
        "business_name": "Sayvors", "title": "Offer", "post_type": "update",
        "description": "Weekend deal", "tags": ["offer"], "keywords": ["deal"],
        "image_urls": [], "cta_type": None, "cta_url": None,
        "action": "draft", "scheduled_on": None,
    }
    data.update(over)
    return data


@pytest.mark.asyncio
async def test_create_draft_and_list(db, user_id):
    res = await posts.create_post(db, user_id, _draft())
    assert res["post"]["status"] == "draft"
    assert res["google_published"] is False
    rows = await posts.list_posts(db, user_id, "loc-1")
    assert len(rows) == 1
    assert rows[0]["title"] == "Offer"


@pytest.mark.asyncio
async def test_create_schedule_requires_future_date(db, user_id):
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    with pytest.raises(ValueError):
        await posts.create_post(db, user_id, _draft(action="schedule", scheduled_on=past))
    with pytest.raises(ValueError):
        await posts.create_post(db, user_id, _draft(action="schedule", scheduled_on=None))


@pytest.mark.asyncio
async def test_publish_now_calls_localith(monkeypatch, db, user_id):
    await _connection(db, user_id)
    calls = []

    def _fake_publish(listing_id, **kw):
        calls.append((listing_id, kw))
        return {"id": "pub-1"}

    monkeypatch.setattr(
        "integrations.channels.embedsocial.publish_media_post", _fake_publish
    )
    created = await posts.create_post(db, user_id, _draft())
    res = await posts.publish_post(db, user_id, created["post"]["id"])
    assert res["google_published"] is True
    assert res["post"]["status"] == "published"
    assert res["post"]["published_at"]
    assert calls[0][0] == "loc-1"
    assert calls[0][1]["caption"] == "Weekend deal"


@pytest.mark.asyncio
async def test_publish_rejects_unconnected_listing(monkeypatch, db, user_id):
    await _connection(db, user_id)

    def _boom(*a, **k):
        raise AssertionError("must not reach Google")

    monkeypatch.setattr(
        "integrations.channels.embedsocial.publish_media_post", _boom
    )
    created = await posts.create_post(db, user_id, _draft(listing_id="other"))
    with pytest.raises(ValueError):
        await posts.publish_post(db, user_id, created["post"]["id"])


@pytest.mark.asyncio
async def test_failed_publish_marks_row(monkeypatch, db, user_id):
    await _connection(db, user_id)

    def _fail(*a, **k):
        raise RuntimeError("Localith exploded")

    monkeypatch.setattr(
        "integrations.channels.embedsocial.publish_media_post", _fail
    )
    created = await posts.create_post(db, user_id, _draft())
    with pytest.raises(RuntimeError):
        await posts.publish_post(db, user_id, created["post"]["id"])
    rows = await posts.list_posts(db, user_id, "loc-1")
    assert rows[0]["status"] == "failed"
    assert "exploded" in (rows[0]["error"] or "")


@pytest.mark.asyncio
async def test_update_and_delete(db, user_id):
    created = await posts.create_post(db, user_id, _draft())
    pid = created["post"]["id"]
    out = await posts.update_post(db, user_id, pid, {"title": "New title"})
    assert out["post"]["title"] == "New title"
    await posts.delete_post(db, user_id, pid)
    assert await posts.list_posts(db, user_id, "loc-1") == []
    with pytest.raises(ValueError):
        await posts.delete_post(db, user_id, pid)


@pytest.mark.asyncio
async def test_publish_due_only_publishes_due(monkeypatch, db, user_id):
    await _connection(db, user_id)
    calls = []

    def _fake_publish(listing_id, **kw):
        calls.append(listing_id)
        return {"id": "pub-x"}

    monkeypatch.setattr(
        "integrations.channels.embedsocial.publish_media_post", _fake_publish
    )
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    future = (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()
    # Bypass the future-date guard by creating drafts then marking scheduled.
    due = await posts.create_post(db, user_id, _draft())
    later = await posts.create_post(db, user_id, _draft())
    await posts.update_post(db, user_id, due["post"]["id"],
                            {"status": "scheduled", "scheduled_on": past})
    await posts.update_post(db, user_id, later["post"]["id"],
                            {"status": "scheduled", "scheduled_on": future})
    totals = await posts.publish_due(db)
    assert totals == {"checked": 1, "published": 1, "failed": 0, "errors": []}
    assert calls == ["loc-1"]


@pytest.mark.asyncio
async def test_cannot_publish_published_or_archived(db, user_id):
    created = await posts.create_post(db, user_id, _draft())
    pid = created["post"]["id"]
    await posts.update_post(db, user_id, pid, {"status": "archived"})
    with pytest.raises(ValueError):
        await posts.publish_post(db, user_id, pid)

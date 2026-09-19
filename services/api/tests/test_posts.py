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
    assert totals == {"checked": 1, "published": 1, "failed": 0,
                      "retried": 0, "skipped": 0, "errors": []}
    assert calls == ["loc-1"]


@pytest.mark.asyncio
async def test_cannot_publish_published_or_archived(db, user_id):
    created = await posts.create_post(db, user_id, _draft())
    pid = created["post"]["id"]
    await posts.update_post(db, user_id, pid, {"status": "archived"})
    with pytest.raises(ValueError):
        await posts.publish_post(db, user_id, pid)


def _future(hours=2):
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


@pytest.mark.asyncio
async def test_delete_at_validation(db, user_id):
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    with pytest.raises(ValueError):
        await posts.create_post(db, user_id, _draft(delete_at=past))
    publish_at = _future(3)
    delete_at = _future(1)
    with pytest.raises(ValueError):
        await posts.create_post(
            db, user_id,
            _draft(action="schedule", scheduled_on=publish_at, delete_at=delete_at),
        )
    res = await posts.create_post(
        db, user_id,
        _draft(action="schedule", scheduled_on=delete_at, delete_at=publish_at,
               end_date=_future(4)),
    )
    assert res["post"]["delete_at"]
    assert res["post"]["end_date"]
    assert res["post"]["status"] == "scheduled"


@pytest.mark.asyncio
async def test_update_delete_at_set_and_cancel(db, user_id):
    created = await posts.create_post(db, user_id, _draft())
    pid = created["post"]["id"]
    out = await posts.update_post(db, user_id, pid, {"delete_at": _future()})
    assert out["post"]["delete_at"]
    # Absent key leaves it untouched.
    out = await posts.update_post(db, user_id, pid, {"title": "T2"})
    assert out["post"]["delete_at"]
    # Explicit null cancels.
    out = await posts.update_post(db, user_id, pid, {"delete_at": None})
    assert out["post"]["delete_at"] is None


@pytest.mark.asyncio
async def test_publish_stores_google_id_and_end_date(monkeypatch, db, user_id):
    await _connection(db, user_id)
    calls = []

    def _fake_publish(listing_id, **kw):
        calls.append(kw)
        return {"id": "pub-9"}

    monkeypatch.setattr(
        "integrations.channels.embedsocial.publish_media_post", _fake_publish
    )
    created = await posts.create_post(db, user_id, _draft(end_date=_future(48)))
    res = await posts.publish_post(db, user_id, created["post"]["id"])
    assert res["post"]["google_post_id"] == "pub-9"
    assert calls[0]["end_date"]


@pytest.mark.asyncio
async def test_retry_then_park(monkeypatch, db, user_id):
    await _connection(db, user_id)

    def _fail(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(
        "integrations.channels.embedsocial.publish_media_post", _fail
    )
    past = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    created = await posts.create_post(db, user_id, _draft())
    pid = created["post"]["id"]
    await posts.update_post(db, user_id, pid, {"status": "scheduled", "scheduled_on": past})
    with pytest.raises(RuntimeError):
        await posts.publish_post(db, user_id, pid)
    rows = await posts.list_posts(db, user_id, "loc-1")
    assert rows[0]["status"] == "scheduled"  # kept for retry, not parked
    totals = await posts.publish_due(db)
    assert totals["checked"] == 0  # backoff not elapsed: skipped silently
    # Exhaust attempts -> parked as failed for the manual Retry button.
    from app.modules.posts.models import LocationPost
    from sqlalchemy import select as _select
    for _ in range(posts.MAX_PUBLISH_ATTEMPTS):
        try:
            await posts.publish_post(db, user_id, pid)
        except RuntimeError:
            pass
    row = (await db.execute(
        _select(LocationPost).where(LocationPost.id == pid)
    )).scalar_one()
    assert row.status == "failed"
    assert row.next_retry_at is None
    totals = await posts.publish_due(db)
    assert totals["checked"] == 0


@pytest.mark.asyncio
async def test_delete_due_removes_only_due(db, user_id):
    from datetime import datetime as _dt
    from app.modules.posts.models import LocationPost

    async def _row(delete_at):
        p = LocationPost(id=f"p-{delete_at is not None}-{len(await posts.list_posts(db, user_id))}",
                         user_id=user_id, listing_id="loc-1", status="scheduled",
                         delete_at=delete_at)
        db.add(p)
        await db.commit()
        return p.id

    now = _dt.now(timezone.utc)
    due_id = await _row(now - timedelta(minutes=1))
    future_id = await _row(now + timedelta(days=1))
    totals = await posts.delete_due(db)
    assert totals == {"checked": 1, "deleted": 1}
    remaining = await posts.list_posts(db, user_id, "loc-1")
    assert [r["id"] for r in remaining] == [future_id]
    assert due_id not in [r["id"] for r in remaining]

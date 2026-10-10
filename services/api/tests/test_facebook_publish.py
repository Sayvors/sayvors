"""Publishing to the tenant's OWN Page feed.

Text and link go to /{page}/feed; photos to /{page}/photos (one published
directly, several as unpublished children + one feed post with
attached_media). `schedule_at` turns anything into a scheduled post via
published=false + unix scheduled_publish_time — and a scheduled photo
ALWAYS schedules on the /feed call, the only response that carries a post
id. All writes pass form data (bracket keys are Graph's canonical form
encoding). A Meta failure is a 502 and nothing partial is ever stored.
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.modules.channels.meta.providers.base import MetaAPIError
from app.modules.channels.meta.providers.facebook import FacebookAdapter

pytestmark = pytest.mark.asyncio

from tests.test_facebook_reads import TENANT, _fb, _seed


def _graph_capture(calls: list, *, feed_error: bool = False, photo_error: bool = False):
    """Record every Graph call — method/path/json/params AND the form data,
    since FB writes ride data=. /photos returns {id, post_id} when published,
    {id} alone when unpublished; /feed always returns a post id."""

    async def _inner(self, method, path, token, **kwargs):
        calls.append({
            "method": method, "path": path,
            "json": kwargs.get("json"), "params": kwargs.get("params"),
            "data": kwargs.get("data"),
        })
        if feed_error and path.endswith("/feed"):
            raise MetaAPIError("feed refused")
        if photo_error and path.endswith("/photos"):
            raise MetaAPIError("photo refused")
        if path.endswith("/photos"):
            data = kwargs.get("data") or {}
            body: dict = {"id": f"photo-{len(calls)}"}
            if data.get("published") != "false":
                body["post_id"] = f"pageid_photo-{len(calls)}"
            return type("R", (), {"json": lambda self: body})()
        if path.endswith("/feed"):
            return type("R", (), {
                "json": lambda self: {"id": f"pageid_post-{len(calls)}"},
            })()
        raise AssertionError(f"unexpected Graph call {method} {path}")

    return _inner


async def test_text_post_is_one_feed_call(db, client, monkeypatch):
    pid = _fb()
    await _seed(db, pid)
    calls: list = []
    monkeypatch.setattr(FacebookAdapter, "_graph", _graph_capture(calls))

    res = client.post(
        f"/api/v1/meta/facebook/{pid}/posts/publish",
        json={"message": "Fresh roast Friday"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body == {
        "post_id": "pageid_post-1",
        "photo_ids": [],
        "scheduled": False,
    }
    assert [c["path"] for c in calls] == [f"/{pid}/feed"]
    assert calls[0]["data"] == {"message": "Fresh roast Friday"}
    assert calls[0]["method"] == "POST"


async def test_link_post_carries_the_link_field(db, client, monkeypatch):
    pid = _fb()
    await _seed(db, pid)
    calls: list = []
    monkeypatch.setattr(FacebookAdapter, "_graph", _graph_capture(calls))

    res = client.post(
        f"/api/v1/meta/facebook/{pid}/posts/publish",
        json={"message": "New blog", "link": "https://sayvors.com/blog/1"},
    )
    assert res.status_code == 200, res.text
    assert calls[0]["data"] == {
        "message": "New blog",
        "link": "https://sayvors.com/blog/1",
    }


async def test_single_photo_publishes_and_prefers_the_post_id(db, client, monkeypatch):
    pid = _fb()
    await _seed(db, pid)
    calls: list = []
    monkeypatch.setattr(FacebookAdapter, "_graph", _graph_capture(calls))

    res = client.post(
        f"/api/v1/meta/facebook/{pid}/posts/publish",
        json={"message": "Latte art", "image_urls": ["https://cdn.example.com/a.jpg"]},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    # /photos returns {id, post_id}; post_id is the feed id the grid lists.
    assert body["post_id"] == "pageid_photo-1"
    assert body["photo_ids"] == ["photo-1"]
    assert [c["path"] for c in calls] == [f"/{pid}/photos"]
    assert calls[0]["data"] == {
        "url": "https://cdn.example.com/a.jpg",
        "caption": "Latte art",
        "published": "true",
    }


async def test_multi_photo_becomes_children_then_one_feed_post(db, client, monkeypatch):
    pid = _fb()
    await _seed(db, pid)
    calls: list = []
    monkeypatch.setattr(FacebookAdapter, "_graph", _graph_capture(calls))

    res = client.post(
        f"/api/v1/meta/facebook/{pid}/posts/publish",
        json={
            "message": "Three shots",
            "image_urls": [
                "https://cdn.example.com/1.jpg",
                "https://cdn.example.com/2.jpg",
                "https://cdn.example.com/3.jpg",
            ],
        },
    )
    assert res.status_code == 200, res.text

    photo_calls = [c for c in calls if c["path"] == f"/{pid}/photos"]
    feed_calls = [c for c in calls if c["path"] == f"/{pid}/feed"]
    assert len(photo_calls) == 3 and len(feed_calls) == 1
    for c in photo_calls:
        assert c["data"]["published"] == "false"
        assert "caption" not in c["data"]
    # Bracket keys ride the form data, in order.
    assert feed_calls[0]["data"] == {
        "message": "Three shots",
        "attached_media[0][media_fbid]": "photo-1",
        "attached_media[1][media_fbid]": "photo-2",
        "attached_media[2][media_fbid]": "photo-3",
    }
    assert res.json()["post_id"] == "pageid_post-4"
    assert res.json()["photo_ids"] == ["photo-1", "photo-2", "photo-3"]


async def test_scheduled_text_sets_published_false_and_unix_seconds(
    db, client, monkeypatch,
):
    pid = _fb()
    await _seed(db, pid)
    calls: list = []
    monkeypatch.setattr(FacebookAdapter, "_graph", _graph_capture(calls))

    when = datetime.now(timezone.utc) + timedelta(hours=2)
    res = client.post(
        f"/api/v1/meta/facebook/{pid}/posts/publish",
        json={"message": "Monday mood", "schedule_at": when.isoformat()},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["scheduled"] is True and body["post_id"] == "pageid_post-1"
    assert calls[0]["data"]["published"] == "false"
    assert calls[0]["data"]["scheduled_publish_time"] == str(int(when.timestamp()))


async def test_scheduled_photo_schedules_on_the_feed_call(db, client, monkeypatch):
    """Unpublished child + /feed carrying the schedule — /photos responses
    have no post id, so a scheduled single photo must NOT stop there."""
    pid = _fb()
    await _seed(db, pid)
    calls: list = []
    monkeypatch.setattr(FacebookAdapter, "_graph", _graph_capture(calls))

    when = datetime.now(timezone.utc) + timedelta(days=3)
    res = client.post(
        f"/api/v1/meta/facebook/{pid}/posts/publish",
        json={
            "message": "Weekend teaser",
            "image_urls": ["https://cdn.example.com/teaser.jpg"],
            "schedule_at": when.isoformat(),
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["scheduled"] is True
    assert body["post_id"] == "pageid_post-2", "the id comes from the feed call"
    assert body["photo_ids"] == ["photo-1"]

    photo_call, feed_call = calls
    assert photo_call["data"]["published"] == "false"
    assert "scheduled_publish_time" not in photo_call["data"]
    assert feed_call["data"]["published"] == "false"
    assert feed_call["data"]["scheduled_publish_time"] == str(int(when.timestamp()))
    assert feed_call["data"]["attached_media[0][media_fbid]"] == "photo-1"


async def test_link_and_images_together_is_422(db, client, monkeypatch):
    pid = _fb()
    await _seed(db, pid)
    calls: list = []
    monkeypatch.setattr(FacebookAdapter, "_graph", _graph_capture(calls))

    res = client.post(
        f"/api/v1/meta/facebook/{pid}/posts/publish",
        json={
            "message": "pick one",
            "link": "https://sayvors.com",
            "image_urls": ["https://cdn.example.com/a.jpg"],
        },
    )
    assert res.status_code == 422
    assert calls == []


async def test_empty_post_is_422(db, client, monkeypatch):
    pid = _fb()
    await _seed(db, pid)
    calls: list = []
    monkeypatch.setattr(FacebookAdapter, "_graph", _graph_capture(calls))

    res = client.post(
        f"/api/v1/meta/facebook/{pid}/posts/publish",
        json={"message": "   "},
    )
    assert res.status_code == 422
    assert calls == []


async def test_schedule_window_is_enforced(db, client, monkeypatch):
    pid = _fb()
    await _seed(db, pid)
    calls: list = []
    monkeypatch.setattr(FacebookAdapter, "_graph", _graph_capture(calls))

    too_soon = (datetime.now(timezone.utc) + timedelta(minutes=2)).isoformat()
    res = client.post(
        f"/api/v1/meta/facebook/{pid}/posts/publish",
        json={"message": "soon", "schedule_at": too_soon},
    )
    assert res.status_code == 422

    too_far = (datetime.now(timezone.utc) + timedelta(days=200)).isoformat()
    res = client.post(
        f"/api/v1/meta/facebook/{pid}/posts/publish",
        json={"message": "far", "schedule_at": too_far},
    )
    assert res.status_code == 422
    assert calls == [], "refused posts never reach Graph"


async def test_more_than_10_images_is_422(db, client, monkeypatch):
    pid = _fb()
    await _seed(db, pid)
    calls: list = []
    monkeypatch.setattr(FacebookAdapter, "_graph", _graph_capture(calls))

    res = client.post(
        f"/api/v1/meta/facebook/{pid}/posts/publish",
        json={"image_urls": [f"https://cdn.example.com/{i}.jpg" for i in range(11)]},
    )
    assert res.status_code == 422
    assert calls == []


async def test_publish_is_tenant_scoped(db, client, monkeypatch):
    other_page = _fb()  # never seeded — belongs to no one
    calls: list = []
    monkeypatch.setattr(FacebookAdapter, "_graph", _graph_capture(calls))

    res = client.post(
        f"/api/v1/meta/facebook/{other_page}/posts/publish",
        json={"message": "hello"},
    )
    assert res.status_code == 404
    assert calls == []


async def test_publish_without_page_token_is_403_not_500(db, client, monkeypatch):
    pid = _fb()
    await _seed(db, pid, with_token=False)
    calls: list = []
    monkeypatch.setattr(FacebookAdapter, "_graph", _graph_capture(calls))

    res = client.post(
        f"/api/v1/meta/facebook/{pid}/posts/publish",
        json={"message": "hello"},
    )
    assert res.status_code == 403
    assert calls == []


async def test_feed_failure_is_502_and_never_partial(db, client, monkeypatch):
    pid = _fb()
    await _seed(db, pid)
    calls: list = []
    monkeypatch.setattr(
        FacebookAdapter, "_graph", _graph_capture(calls, feed_error=True)
    )

    res = client.post(
        f"/api/v1/meta/facebook/{pid}/posts/publish",
        json={
            "message": "multi",
            "image_urls": [
                "https://cdn.example.com/1.jpg",
                "https://cdn.example.com/2.jpg",
            ],
        },
    )
    assert res.status_code == 502
    assert "feed refused" in res.json()["detail"]
    # The children were attempted, the /feed call was attempted and raised —
    # nothing live, nothing stored, and Meta's message is what the tenant sees.
    assert [c["path"] for c in calls] == [
        f"/{pid}/photos", f"/{pid}/photos", f"/{pid}/feed",
    ]

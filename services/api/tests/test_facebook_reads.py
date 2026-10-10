"""Facebook Page hub reads: profile, feed, scheduled — and the cache.

Same contract as the IG hub reads: Graph rows mapped faithfully, a second
read inside the TTL served from redis without touching Graph, `refresh=1`
bypassing it, and a missing page token degrading the grid read to
`unavailable` (the profile read is a loud 403 instead — without a token
nothing on this Page works). The page token lives on the ASSET row, never
the connection.

Each test mints its own page id — redis outlives a single test, and a
shared fixture id would hand one test another test's cached copy.
"""
import uuid

import httpx
import pytest

from app.config import settings
from app.modules.channels.meta.credentials import encrypt_credential
from app.modules.channels.meta.models import MetaAsset, MetaConnection
from app.modules.channels.meta.providers.facebook import FacebookAdapter

pytestmark = pytest.mark.asyncio

TENANT = "test-user-0000-0000-0000-000000000001"  # conftest's authenticated user


def _fb() -> str:
    return f"1009{uuid.uuid4().int % 10_000_000_000_000:013d}"


async def _seed(db, page_id: str, *, with_token: bool = True) -> None:
    conn = MetaConnection(
        id=str(uuid.uuid4()),
        tenant_id=TENANT,
        provider="facebook",
        access_token_encrypted=encrypt_credential("user-token"),
        status="active",
    )
    db.add(conn)
    await db.flush()
    db.add(
        MetaAsset(
            id=str(uuid.uuid4()),
            tenant_id=TENANT,
            connection_id=conn.id,
            provider="facebook",
            asset_type="page",
            external_asset_id=page_id,
            name="Sayvors Page",
            active=True,
            # The PAGE token rides the asset metadata — discovery stored it
            # at connect time. The connection holds the user/business token.
            asset_metadata={"page_access_token": "page-token"} if with_token else {},
        )
    )
    await db.commit()


def _fake_graph(calls: dict, payload: dict):
    async def _inner(self, method, path, token, **kwargs):
        calls["n"] += 1
        return httpx.Response(200, json=payload)

    return _inner


async def _flush_cache(kind: str, page_id: str) -> None:
    from app.modules.redis.client import get_redis

    await (await get_redis()).delete(f"ig:{kind}:{page_id}")


@pytest.fixture(autouse=True)
def _cache_enabled(monkeypatch):
    """The cache is TESTING-gated; these tests exercise it for real."""
    monkeypatch.setattr(settings, "TESTING", False)


async def test_profile_read_maps_the_page_fields(db, client, monkeypatch):
    pid = _fb()
    await _seed(db, pid)
    calls = {"n": 0}
    payload = {
        "id": pid,
        "name": "Sayvors Page",
        "fan_count": 120,
        "followers_count": 4500,
        "link": f"https://facebook.com/{pid}",
        "picture": {"data": {"url": "https://cdn.facebook.com/pic.jpg"}},
    }
    monkeypatch.setattr(FacebookAdapter, "_graph", _fake_graph(calls, payload))

    res = client.get(f"/api/v1/meta/facebook/{pid}/profile")

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["id"] == pid
    assert body["name"] == "Sayvors Page"
    assert body["fan_count"] == 120
    assert body["followers_count"] == 4500
    # Meta nests the picture url one level down; the API flattens it.
    assert body["profile_picture_url"] == "https://cdn.facebook.com/pic.jpg"
    assert body["link"] == f"https://facebook.com/{pid}"
    await _flush_cache("fb_profile", pid)


async def test_posts_read_maps_feed_rows(db, client, monkeypatch):
    pid = _fb()
    await _seed(db, pid)
    calls = {"n": 0}
    row = {
        "id": f"{pid}_101",
        "message": "New roast landed",
        "created_time": "2026-01-01T00:00:00+0000",
        "permalink_url": f"https://facebook.com/{pid}/posts/101",
        "full_picture": "https://cdn.facebook.com/thumb.jpg",
        "from": {"id": pid, "name": "Sayvors Page"},
        "likes": {"summary": {"total_count": 7}},
        "comments": {"summary": {"total_count": 2}},
        "attachments": {"data": [{
            "media_type": "photo",
            "media": {"image": {"src": "https://cdn.facebook.com/big.jpg"}},
            "subattachments": {"data": [
                {"media": {"image": {"src": "https://cdn.facebook.com/s1.jpg"}}},
                {"media": {"image": {"src": "https://cdn.facebook.com/s2.jpg"}}},
            ]},
        }]},
    }
    monkeypatch.setattr(
        FacebookAdapter, "_graph", _fake_graph(calls, {"data": [row]})
    )

    res = client.get(f"/api/v1/meta/facebook/{pid}/posts")

    assert res.status_code == 200, res.text
    post = res.json()["posts"][0]
    assert post["id"] == f"{pid}_101"
    assert post["message"] == "New roast landed"
    assert post["from_name"] == "Sayvors Page"
    assert post["like_count"] == 7
    assert post["comments_count"] == 2
    assert post["permalink_url"].endswith("/posts/101")
    # Top-level attachment media first, then every carousel slide.
    assert post["images"] == [
        "https://cdn.facebook.com/big.jpg",
        "https://cdn.facebook.com/s1.jpg",
        "https://cdn.facebook.com/s2.jpg",
    ]
    await _flush_cache("fb_posts", pid)


async def test_missing_page_token_degrades_posts_and_blocks_profile(
    db, client, monkeypatch,
):
    pid = _fb()
    await _seed(db, pid, with_token=False)
    calls = {"n": 0}
    monkeypatch.setattr(
        FacebookAdapter, "_graph", _fake_graph(calls, {"data": []})
    )

    res = client.get(f"/api/v1/meta/facebook/{pid}/posts")
    assert res.status_code == 200
    assert res.json()["unavailable"], "the grid degrades with a reason"
    assert calls["n"] == 0, "no Graph call without a token"

    res = client.get(f"/api/v1/meta/facebook/{pid}/profile")
    assert res.status_code == 403, "the profile read is loud, not blank"


async def test_second_posts_read_is_served_from_cache(db, client, monkeypatch):
    pid = _fb()
    await _seed(db, pid)
    calls = {"n": 0}
    row = {
        "id": f"{pid}_202",
        "message": "hello",
        "created_time": "2026-01-02T00:00:00+0000",
        "likes": {"summary": {"total_count": 1}},
        "comments": {"summary": {"total_count": 0}},
    }
    monkeypatch.setattr(
        FacebookAdapter, "_graph", _fake_graph(calls, {"data": [row]})
    )

    first = client.get(f"/api/v1/meta/facebook/{pid}/posts")
    second = client.get(f"/api/v1/meta/facebook/{pid}/posts")

    assert first.status_code == 200 and second.status_code == 200
    assert calls["n"] == 1, "the second read inside the TTL must hit redis"
    assert second.json()["posts"][0]["message"] == "hello"
    await _flush_cache("fb_posts", pid)


async def test_scheduled_read_maps_unix_times(db, client, monkeypatch):
    pid = _fb()
    await _seed(db, pid)
    calls = {"n": 0}
    monkeypatch.setattr(
        FacebookAdapter, "_graph",
        _fake_graph(calls, {"data": [{"id": f"{pid}_55", "scheduled_publish_time": 1767225600}]}),
    )

    res = client.get(f"/api/v1/meta/facebook/{pid}/scheduled")

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["posts"] == [{"id": f"{pid}_55", "scheduled_publish_time": 1767225600}]
    assert calls["n"] == 1
    await _flush_cache("fb_scheduled", pid)

"""Instagram read cache: tab clicks must not become Graph calls.

The hub's five tabs (Posts and Comments doubly so — both read /posts) can
burn an account's IG rate budget on clicks alone. These tests pin the
contract: a second read inside the TTL is served from redis without touching
Graph, ?refresh=1 always re-reads, and a dead redis degrades to a live fetch
instead of failing the request.

Each test mints its own IG id — redis outlives a single test, and a shared
fixture id would hand one test another test's cached copy.
"""
import uuid
from unittest.mock import AsyncMock

import httpx
import pytest

from app.config import settings
from app.modules.channels.meta.credentials import encrypt_credential
from app.modules.channels.meta.models import MetaAsset, MetaConnection
from app.modules.channels.meta.providers.instagram import InstagramAdapter

pytestmark = pytest.mark.asyncio

TENANT = "test-user-0000-0000-0000-000000000001"  # conftest's authenticated user


def _ig() -> str:
    return f"1784141{uuid.uuid4().int % 10_000_000_000:010d}"


def _profile_payload(ig: str) -> dict:
    return {
        "id": ig,
        "username": "sayvors",
        "name": "Sayvors",
        "biography": None,
        "website": None,
        "profile_picture_url": None,
        "followers_count": 12400,
        "follows_count": 845,
        "media_count": 234,
    }


def _fake_graph(calls: dict, payload: dict):
    async def _inner(self, method, path, token, **kwargs):
        calls["n"] += 1
        return httpx.Response(200, json=payload)

    return _inner


async def _seed(db, ig: str) -> None:
    conn = MetaConnection(
        id=str(uuid.uuid4()),
        tenant_id=TENANT,
        provider="instagram",
        access_token_encrypted=encrypt_credential("page-token"),
        status="active",
    )
    db.add(conn)
    await db.flush()
    db.add(
        MetaAsset(
            id=str(uuid.uuid4()),
            tenant_id=TENANT,
            connection_id=conn.id,
            provider="instagram",
            asset_type="ig_account",
            external_asset_id=ig,
            name="sayvors",
            username="sayvors",
            active=True,
            asset_metadata={},
        )
    )
    await db.commit()


async def _flush_cache(kind: str, ig: str) -> None:
    from app.modules.redis.client import get_redis

    await (await get_redis()).delete(f"ig:{kind}:{ig}")


@pytest.fixture(autouse=True)
def _cache_enabled(monkeypatch):
    """The cache is TESTING-gated; these tests exercise it for real."""
    monkeypatch.setattr(settings, "TESTING", False)


async def test_second_profile_read_is_served_from_cache(client, db, monkeypatch):
    ig = _ig()
    await _seed(db, ig)
    calls = {"n": 0}
    monkeypatch.setattr(
        InstagramAdapter, "_graph", _fake_graph(calls, _profile_payload(ig))
    )

    first = client.get(f"/api/v1/meta/instagram/{ig}/profile")
    second = client.get(f"/api/v1/meta/instagram/{ig}/profile")

    assert first.status_code == 200 and second.status_code == 200
    assert calls["n"] == 1, "the second read inside the TTL must hit redis"
    assert second.json()["followers_count"] == first.json()["followers_count"]
    assert second.json()["stale"] is False
    await _flush_cache("profile", ig)


async def test_refresh_bypasses_the_cache(client, db, monkeypatch):
    ig = _ig()
    await _seed(db, ig)
    calls = {"n": 0}
    monkeypatch.setattr(
        InstagramAdapter, "_graph", _fake_graph(calls, _profile_payload(ig))
    )

    client.get(f"/api/v1/meta/instagram/{ig}/profile")
    client.get(f"/api/v1/meta/instagram/{ig}/profile?refresh=true")

    assert calls["n"] == 2, "an explicit refresh must re-read Graph"
    await _flush_cache("profile", ig)


async def test_igcache_swallows_redis_outages(monkeypatch):
    """The cache is best-effort by contract: a dead redis is a cache miss,
    never an error. Tested directly — patching the shared redis client would
    also take down the auth blacklist, which fails closed by design."""

    async def _down():
        raise ConnectionError("redis unavailable")

    monkeypatch.setattr("app.modules.redis.client.get_redis", _down)

    from app.modules.channels.meta import igcache

    assert await igcache.get("profile", "some-ig-id") is None
    # The write path must not raise either.
    await igcache.set("profile", "some-ig-id", {"username": "sayvors"}, 60)


async def test_second_posts_read_is_served_from_cache(client, db, monkeypatch):
    ig = _ig()
    await _seed(db, ig)
    calls = {"n": 0}
    payload = {
        "id": "17900000000000001",
        "caption": "hello",
        "media_type": "IMAGE",
        "media_url": None,
        "permalink": "https://instagram.com/p/xyz",
        "timestamp": "2026-01-01T00:00:00+00:00",
        "like_count": 3,
        "comments_count": 1,
        "comments": [
            {
                "id": "c1",
                "text": "nice",
                "username": "fan",
                "name": None,
                "ig_id": "123",
                "like_count": 0,
                "timestamp": "2026-01-01T01:00:00+00:00",
                "hidden": False,
                "media_id": "17900000000000001",
                "profile_url": "https://instagram.com/fan",
            }
        ],
    }

    async def _posts(self, ig_id, token, **kwargs):
        calls["n"] += 1
        return [dict(payload)]

    monkeypatch.setattr(InstagramAdapter, "get_recent_posts", _posts)

    first = client.get(f"/api/v1/meta/instagram/{ig}/posts")
    second = client.get(f"/api/v1/meta/instagram/{ig}/posts")

    assert first.status_code == 200 and second.status_code == 200
    assert calls["n"] == 1
    assert second.json()["posts"][0]["comments"][0]["username"] == "fan"
    await _flush_cache("posts", ig)


async def test_second_audience_read_is_served_from_cache(client, db, monkeypatch):
    ig = _ig()
    await _seed(db, ig)
    calls = {"n": 0}

    async def _commenters(self, ig_id, token, **kwargs):
        calls["n"] += 1
        return [
            {
                "source": "comment",
                "ig_id": "999",
                "username": "fan",
                "name": "Fan",
                "text": "love this",
                "like_count": 1,
                "occurred_at": "2026-01-01T00:00:00+00:00",
                "media_id": "m1",
                "permalink": "https://instagram.com/p/x",
                "profile_url": "https://instagram.com/fan",
            }
        ]

    async def _demo(self, ig_id, token, **kwargs):
        return {"age": [], "gender": [], "cities": [], "countries": []}

    monkeypatch.setattr(InstagramAdapter, "get_recent_commenters", _commenters)
    monkeypatch.setattr(InstagramAdapter, "get_follower_demographics", _demo)

    first = client.get(f"/api/v1/meta/instagram/{ig}/audience")
    second = client.get(f"/api/v1/meta/instagram/{ig}/audience")

    assert first.status_code == 200 and second.status_code == 200
    assert calls["n"] == 1
    assert second.json()["people"][0]["username"] == "fan"
    await _flush_cache("audience", ig)


async def test_unreachable_graph_is_not_cached(client, db, monkeypatch):
    """A failure must not poison the cache: the next read goes live again."""
    from app.modules.channels.meta.providers.base import MetaAPIError

    ig = _ig()
    await _seed(db, ig)
    calls = {"n": 0}

    # Mocked at the adapter method (not _graph): get_business_profile itself
    # retries minimal fields on failure, which would double the call count.
    async def _flaky(self, ig_id, token):
        calls["n"] += 1
        if calls["n"] == 1:
            raise MetaAPIError("upstream 500", 500)
        return _profile_payload(ig)

    monkeypatch.setattr(InstagramAdapter, "get_business_profile", _flaky)

    first = client.get(f"/api/v1/meta/instagram/{ig}/profile")
    second = client.get(f"/api/v1/meta/instagram/{ig}/profile")

    # The failure still surfaces (no snapshot seeded), but nothing was cached.
    assert first.status_code == 500
    assert second.status_code == 200
    assert calls["n"] == 2
    await _flush_cache("profile", ig)

"""Stories and per-post insights — the last owner-only reads the API offers.

Stories: only the account's OWN live stories exist; an empty tray is a normal
answer, not an error. Insights: owner-only and metric availability differs by
media type, so an unavailable answer (available=false + reason) is also
normal. Both follow the read-cache contract, so a second read inside the TTL
never touches Graph.
"""
from unittest.mock import AsyncMock

import pytest

from app.config import settings
from app.modules.channels.meta.models import MetaConnection
from app.modules.channels.meta.providers.instagram import InstagramAdapter

pytestmark = pytest.mark.asyncio

from tests.test_instagram_read_cache import TENANT, _flush_cache, _ig, _seed


@pytest.fixture(autouse=True)
def _cache_enabled(monkeypatch):
    monkeypatch.setattr(settings, "TESTING", False)


async def test_stories_return_live_and_are_cached(client, db, monkeypatch):
    ig = _ig()
    await _seed(db, ig)
    stories = [
        {"id": "s1", "media_type": "IMAGE", "media_url": "https://cdn/s1.jpg", "timestamp": "2026-10-08T09:00:00+00:00"}
    ]
    monkeypatch.setattr(
        InstagramAdapter, "get_stories", AsyncMock(return_value=stories)
    )

    first = client.get(f"/api/v1/meta/instagram/{ig}/stories")
    second = client.get(f"/api/v1/meta/instagram/{ig}/stories")

    assert first.status_code == 200 and second.status_code == 200
    assert first.json()["stories"][0]["id"] == "s1"
    assert InstagramAdapter.get_stories.await_count == 1, "second read must hit redis"
    await _flush_cache("stories", ig)


async def test_stories_without_token_is_empty_not_error(client, db):
    ig = _ig()
    await _seed(db, ig)
    # One connection per (tenant, provider), so null the seeded token instead
    # of adding a second connection.
    from sqlalchemy import select

    conn = (await db.execute(select(MetaConnection).where(MetaConnection.tenant_id == TENANT))).scalar_one()
    conn.access_token_encrypted = None
    await db.commit()

    res = client.get(f"/api/v1/meta/instagram/{ig}/stories")
    assert res.status_code == 200
    assert res.json() == {"stories": []}


async def test_insights_map_metrics_and_cache(client, db, monkeypatch):
    ig = _ig()
    await _seed(db, ig)
    monkeypatch.setattr(
        InstagramAdapter,
        "get_media_insights",
        AsyncMock(return_value={"impressions": 1200, "reach": 980, "saved": 41, "shares": 7}),
    )

    first = client.get(f"/api/v1/meta/instagram/{ig}/media/m1/insights?media_type=REELS")
    second = client.get(f"/api/v1/meta/instagram/{ig}/media/m1/insights?media_type=REELS")

    body = first.json()
    assert first.status_code == 200
    assert body["available"] is True
    assert body["impressions"] == 1200
    assert body["saves"] == 41
    assert body["shares"] == 7
    assert InstagramAdapter.get_media_insights.await_count == 1
    await _flush_cache("insights", "m1")


async def test_insights_unavailable_is_a_normal_answer(client, db, monkeypatch):
    ig = _ig()
    await _seed(db, ig)
    monkeypatch.setattr(
        InstagramAdapter, "get_media_insights", AsyncMock(return_value={})
    )

    res = client.get(f"/api/v1/meta/instagram/{ig}/media/m2/insights")

    assert res.status_code == 200
    body = res.json()
    assert body["available"] is False
    assert body["reason"]
    await _flush_cache("insights", "m2")

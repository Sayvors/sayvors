"""Publishing to the tenant's own Instagram feed.

Container → publish is two Graph calls: one url posts directly, several
become a carousel (children first, then the carousel container, and per
Meta's rule the caption rides ONLY the carousel). Meta failures surface as
502 — there is no partial post to store — and the tenant boundary is the
same 404 every other IG endpoint draws. The publishing-limit read degrades
to zeros when Meta refuses, like every other read.
"""
import pytest
from sqlalchemy import select

from app.modules.channels.meta.credentials import encrypt_credential
from app.modules.channels.meta.models import MetaConnection
from app.modules.channels.meta.providers.base import MetaAPIError
from app.modules.channels.meta.providers.instagram import InstagramAdapter

pytestmark = pytest.mark.asyncio

from conftest import TEST_SESSION
from tests.test_instagram_read_cache import TENANT, _ig, _seed


def _graph_capture(
    calls: list, *, media_error: bool = False, publish_error: bool = False,
    story_error: bool = False, search_data: list | None = None,
):
    """Record every Graph call; hand back fresh container ids, then a
    published media id. Selectively fails a step to pin the 502 path."""

    async def _inner(self, method, path, token, **kwargs):
        calls.append({
            "method": method, "path": path,
            "json": kwargs.get("json"), "params": kwargs.get("params"),
        })
        if media_error and path.endswith("/media"):
            raise MetaAPIError("media container refused")
        if publish_error and path.endswith("/media_publish"):
            raise MetaAPIError("publish refused")
        if story_error and path.endswith("/media") and (
            (kwargs.get("json") or {}).get("media_type") == "STORIES"
        ):
            raise MetaAPIError("story container refused")
        if path.endswith("/media_publish"):
            return type("R", (), {"json": lambda self: {"id": "published-media-9"}})()
        if path.endswith("/media"):
            return type("R", (), {
                "json": lambda self: {"id": f"cont-{len(calls)}"},
            })()
        if path.endswith("/content_publishing_limit"):
            return type("R", (), {
                "json": lambda self: {"quota_total": 50, "quota_usage": 3},
            })()
        if path == "/search":
            return type("R", (), {"json": lambda self: {"data": search_data or []}})()
        raise AssertionError(f"unexpected Graph call {method} {path}")

    return _inner


async def test_single_image_publish_is_two_graph_calls(db, client, monkeypatch):
    ig = _ig()
    await _seed(db, ig)
    calls: list = []
    monkeypatch.setattr(
        InstagramAdapter, "_graph", _graph_capture(calls)
    )

    res = client.post(
        f"/api/v1/meta/instagram/{ig}/posts/publish",
        json={"image_urls": ["https://cdn.example.com/photo.jpg"], "caption": "Hello feed"},
    )
    assert res.status_code == 200, res.text
    assert res.json() == {"media_id": "published-media-9", "story_media_ids": []}

    assert [c["path"] for c in calls] == [f"/{ig}/media", f"/{ig}/media_publish"]
    assert calls[0]["json"] == {
        "image_url": "https://cdn.example.com/photo.jpg",
        "caption": "Hello feed",
    }
    assert calls[1]["json"] == {"creation_id": "cont-1"}


async def test_multi_url_becomes_carousel_with_caption_on_carousel_only(db, client, monkeypatch):
    ig = _ig()
    await _seed(db, ig)
    calls: list = []
    monkeypatch.setattr(
        InstagramAdapter, "_graph", _graph_capture(calls)
    )

    res = client.post(
        f"/api/v1/meta/instagram/{ig}/posts/publish",
        json={
            "image_urls": [
                "https://cdn.example.com/1.jpg",
                "https://cdn.example.com/2.jpg",
                "https://cdn.example.com/3.jpg",
            ],
            "caption": "Three shots",
        },
    )
    assert res.status_code == 200, res.text

    media_calls = [c for c in calls if c["path"] == f"/{ig}/media"]
    assert len(media_calls) == 4  # three children, then the carousel
    for child in media_calls[:3]:
        assert child["json"]["is_carousel_item"] is True
        assert "caption" not in child["json"]
    carousel = media_calls[3]
    assert carousel["json"]["media_type"] == "CAROUSEL_ALBUM"
    assert carousel["json"]["children"] == "cont-1,cont-2,cont-3"
    assert carousel["json"]["caption"] == "Three shots"
    # Publish rides the carousel container id (cont-4 = the last media call).
    assert calls[-1]["path"] == f"/{ig}/media_publish"
    assert calls[-1]["json"] == {"creation_id": "cont-4"}


async def test_container_failure_is_502_and_never_publishes(db, client, monkeypatch):
    ig = _ig()
    await _seed(db, ig)
    calls: list = []
    monkeypatch.setattr(
        InstagramAdapter, "_graph",
        _graph_capture(calls, media_error=True),
    )

    res = client.post(
        f"/api/v1/meta/instagram/{ig}/posts/publish",
        json={"image_urls": ["https://cdn.example.com/x.jpg"], "caption": ""},
    )
    assert res.status_code == 502
    assert "media container refused" in res.json()["detail"]
    assert all(c["path"] != f"/{ig}/media_publish" for c in calls)


async def test_publish_step_failure_is_502(db, client, monkeypatch):
    ig = _ig()
    await _seed(db, ig)
    calls: list = []
    monkeypatch.setattr(
        InstagramAdapter, "_graph",
        _graph_capture(calls, publish_error=True),
    )

    res = client.post(
        f"/api/v1/meta/instagram/{ig}/posts/publish",
        json={"image_urls": ["https://cdn.example.com/x.jpg"], "caption": ""},
    )
    assert res.status_code == 502
    assert "publish refused" in res.json()["detail"]


async def test_publish_is_tenant_scoped(db, client, monkeypatch):
    other_ig = _ig()  # never seeded — belongs to no one
    calls: list = []
    monkeypatch.setattr(
        InstagramAdapter, "_graph", _graph_capture(calls)
    )

    res = client.post(
        f"/api/v1/meta/instagram/{other_ig}/posts/publish",
        json={"image_urls": ["https://cdn.example.com/x.jpg"], "caption": ""},
    )
    assert res.status_code == 404
    assert calls == []


async def test_publish_without_token_is_403_not_500(db, client, monkeypatch):
    ig = _ig()
    await _seed(db, ig)
    async with TEST_SESSION() as session:
        conn = (
            await session.execute(
                select(MetaConnection).where(MetaConnection.tenant_id == TENANT)
            )
        ).scalars().first()
        conn.access_token_encrypted = None
        session.add(conn)
        await session.commit()

    calls: list = []
    monkeypatch.setattr(
        InstagramAdapter, "_graph", _graph_capture(calls)
    )

    res = client.post(
        f"/api/v1/meta/instagram/{ig}/posts/publish",
        json={"image_urls": ["https://cdn.example.com/x.jpg"], "caption": ""},
    )
    assert res.status_code == 403
    assert calls == []


async def test_publishing_limit_reads_quota_and_degrades_to_zeros(db, client, monkeypatch):
    ig = _ig()
    await _seed(db, ig)
    calls: list = []
    monkeypatch.setattr(
        InstagramAdapter, "_graph", _graph_capture(calls)
    )

    res = client.get(f"/api/v1/meta/instagram/{ig}/publishing-limit")
    assert res.status_code == 200
    assert res.json() == {"quota_total": 50, "quota_usage": 3}
    assert calls[0]["path"] == f"/{ig}/content_publishing_limit"

    async def _refused(self, method, path, token, **kwargs):
        raise MetaAPIError("scope missing")

    monkeypatch.setattr(InstagramAdapter, "_graph", _refused)
    res = client.get(f"/api/v1/meta/instagram/{ig}/publishing-limit")
    assert res.status_code == 200
    assert res.json() == {"quota_total": 0, "quota_usage": 0}


async def test_publish_carries_location_share_and_alt_text(db, client, monkeypatch):
    ig = _ig()
    await _seed(db, ig)
    calls: list = []
    monkeypatch.setattr(
        InstagramAdapter, "_graph",
        _graph_capture(calls, search_data=[]),
    )

    res = client.post(
        f"/api/v1/meta/instagram/{ig}/posts/publish",
        json={
            "image_urls": ["https://cdn.example.com/x.jpg"],
            "caption": "At the shop",
            "location_id": "page-loc-1",
            "share_to_facebook": True,
            "alt_text": "A latte on the counter",
        },
    )
    assert res.status_code == 200, res.text
    assert calls[0]["json"]["location_id"] == "page-loc-1"
    assert calls[0]["json"]["share_to_facebook"] is True
    assert calls[0]["json"]["alt_text"] == "A latte on the counter"


async def test_story_images_publish_after_the_feed_post(db, client, monkeypatch):
    ig = _ig()
    await _seed(db, ig)
    calls: list = []
    monkeypatch.setattr(
        InstagramAdapter, "_graph",
        _graph_capture(calls, search_data=[]),
    )

    res = client.post(
        f"/api/v1/meta/instagram/{ig}/posts/publish",
        json={
            "image_urls": ["https://cdn.example.com/x.jpg"],
            "caption": "",
            "story_image_urls": ["https://cdn.example.com/story-916.jpg"],
        },
    )
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["media_id"] == "published-media-9"
    assert out["story_media_ids"] == ["published-media-9"]
    # Feed container → feed publish → story container (9:16, STORIES) →
    # story publish — the feed post is never held hostage by the story.
    assert [c["path"] for c in calls] == [
        f"/{ig}/media", f"/{ig}/media_publish",
        f"/{ig}/media", f"/{ig}/media_publish",
    ]
    assert calls[2]["json"] == {
        "image_url": "https://cdn.example.com/story-916.jpg",
        "media_type": "STORIES",
    }


async def test_story_failure_does_not_fail_the_feed_post(db, client, monkeypatch):
    ig = _ig()
    await _seed(db, ig)
    calls: list = []
    monkeypatch.setattr(
        InstagramAdapter, "_graph",
        _graph_capture(calls, search_data=[], story_error=True),
    )

    res = client.post(
        f"/api/v1/meta/instagram/{ig}/posts/publish",
        json={
            "image_urls": ["https://cdn.example.com/x.jpg"],
            "caption": "",
            "story_image_urls": ["https://cdn.example.com/story-916.jpg"],
        },
    )
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["media_id"] == "published-media-9"
    assert len(out["story_media_ids"]) == 1
    assert out["story_media_ids"][0].startswith("failed:")


async def test_location_search_and_degrade(db, client, monkeypatch):
    ig = _ig()
    await _seed(db, ig)
    calls: list = []
    monkeypatch.setattr(
        InstagramAdapter, "_graph",
        _graph_capture(calls, search_data=[{"id": "111", "name": "Paris"}]),
    )

    res = client.get(f"/api/v1/meta/instagram/{ig}/locations?q=paris")
    assert res.status_code == 200
    assert res.json() == {"locations": [{"id": "111", "name": "Paris"}]}
    assert calls[0]["params"]["type"] == "place"
    assert calls[0]["params"]["q"] == "paris"

    async def _refused(self, method, path, token, **kwargs):
        raise MetaAPIError("search not allowed")

    monkeypatch.setattr(InstagramAdapter, "_graph", _refused)
    res = client.get(f"/api/v1/meta/instagram/{ig}/locations?q=paris")
    assert res.status_code == 200
    assert res.json() == {"locations": []}


async def test_caption_suggest_uses_tenant_model(db, client, monkeypatch):
    ig = _ig()
    await _seed(db, ig)

    import app.modules.llm.providers.registry as registry
    import app.modules.llm.service as llm_service

    class _Resp:
        content = "Fresh roast, new drop ☕ #sayvors"

    class _Provider:
        async def complete(self, req):
            return _Resp()

    async def _model(db_, preferred=None):
        return "catalog:test-model"

    monkeypatch.setattr(llm_service, "resolve_tenant_model", _model)
    monkeypatch.setattr(registry, "get_provider_for_model", lambda mid: _Provider())

    res = client.post(
        f"/api/v1/meta/instagram/{ig}/caption/suggest",
        json={"hint": "a latte on the counter", "current_caption": ""},
    )
    assert res.status_code == 200, res.text
    assert res.json()["caption"].startswith("Fresh roast")


async def test_caption_suggest_without_model_is_400(db, client, monkeypatch):
    ig = _ig()
    await _seed(db, ig)

    import app.modules.llm.service as llm_service

    async def _none(db_, preferred=None):
        raise ValueError("No AI model is enabled by your administrator.")

    monkeypatch.setattr(llm_service, "resolve_tenant_model", _none)

    res = client.post(
        f"/api/v1/meta/instagram/{ig}/caption/suggest",
        json={"hint": "", "current_caption": ""},
    )
    assert res.status_code == 400
    assert "No AI model" in res.json()["detail"]

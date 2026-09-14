"""Facebook asset discovery: a Page returned by /me/accounts must surface.

Regression: the adapter must request page tokens (access_token/tasks) and
turn each returned Page into a DiscoveredAsset carrying its page token.
"""
import httpx
import pytest

from app.modules.channels.meta.providers.facebook import FacebookAdapter

pytestmark = pytest.mark.asyncio

_PAGE = {
    "id": "page-1",
    "name": "Test Page",
    "link": "https://facebook.com/testpage",
    "access_token": "page-token-xyz",
    "tasks": ["MANAGE", "CREATE_CONTENT"],
}


def _fake_graph(payload, seen):
    async def _inner(self, method, path, token, **kwargs):
        seen["method"] = method
        seen["path"] = path
        seen["params"] = kwargs.get("params", {})
        seen["token_present"] = bool(token)
        return httpx.Response(200, json=payload)

    return _inner


async def test_discover_returns_page_with_token(monkeypatch):
    seen: dict = {}
    monkeypatch.setattr(
        FacebookAdapter, "_graph", _fake_graph({"data": [_PAGE]}, seen)
    )

    out = await FacebookAdapter().discover_assets({"access_token": "biz-token"})

    assert seen["method"] == "GET"
    assert seen["path"] == "/me/accounts"
    assert seen["params"].get("fields") == "id,name,link,access_token,tasks"
    assert seen["token_present"] is True
    assert len(out) == 1
    assert out[0].asset_type == "page"
    assert out[0].external_asset_id == "page-1"
    assert out[0].name == "Test Page"
    assert out[0].extra["page_access_token"] == "page-token-xyz"


async def test_discover_empty_when_no_pages(monkeypatch):
    seen: dict = {}
    monkeypatch.setattr(
        FacebookAdapter, "_graph", _fake_graph({"data": []}, seen)
    )

    out = await FacebookAdapter().discover_assets({"access_token": "biz-token"})
    assert out == []

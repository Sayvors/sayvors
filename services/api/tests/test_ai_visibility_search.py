"""Bounded public search with cache, rate limits, and no API key."""
import pytest

from app.modules.ai_visibility import search


RSS = b"""<?xml version="1.0"?>
<rss version="2.0"><channel>
<item><title>Acme Coffee</title><link>https://acme.example/coffee</link>
<description>Fresh coffee near Malqa.</description></item>
<item><title>Rival Coffee</title><link>https://rival.example/</link>
<description>Another coffee shop.</description></item>
</channel></rss>"""


def test_parse_bing_rss_is_bounded_and_deduped():
    duplicate = RSS.replace(
        b"</channel>",
        b"<item><title>Acme Coffee</title><link>https://acme.example/coffee</link>"
        b"<description>Duplicate.</description></item></channel>",
    )
    results = search.parse_bing_rss(duplicate)
    assert len(results) == 2
    assert results[0].title == "Acme Coffee"
    assert results[0].url == "https://acme.example/coffee"


def test_normalize_query_is_stable():
    assert search.normalize_query("  Best   COFFEE near Malqa ") == "best coffee near malqa"


def test_rejects_non_http_results():
    results = [
        search.SearchResult(url="javascript:alert(1)", title="bad", snippet=""),
        search.SearchResult(url="https://example.com", title="ok", snippet=""),
    ]
    assert [row.url for row in search.safe_results(results)] == ["https://example.com"]


def test_parse_bing_html_fallback():
    html = b"""<html><body><li class="b_algo"><h2>
    <a href="https://example.com">Example</a></h2>
    <p>Useful evidence.</p></li></body></html>"""
    rows = search.parse_bing_html(html)
    assert rows[0].url == "https://example.com"
    assert rows[0].title == "Example"
    assert rows[0].snippet == "Useful evidence."


@pytest.mark.asyncio
async def test_cache_is_served_while_provider_is_blocked(monkeypatch):
    async def _cache_get(key):
        if key.endswith(":blocked"):
            return "1"
        return '[{"url": "https://example.com/cached", "title": "Cached", "snippet": "x"}]'

    async def _unexpected(*_args, **_kwargs):
        raise AssertionError("cached results must not consume provider quota")

    monkeypatch.setattr(search, "cache_get", _cache_get)
    monkeypatch.setattr(search, "rate_limit", _unexpected)
    monkeypatch.setattr(search, "_fetch_results", _unexpected)

    results = await search.search_public_web("tenant", "best coffee")
    assert results[0].url == "https://example.com/cached"


@pytest.mark.asyncio
async def test_search_enforces_a_per_tenant_limit(monkeypatch):
    keys = []

    async def _cache_get(_key):
        return None

    async def _limit(key, *_args, **_kwargs):
        keys.append(key)
        return False

    monkeypatch.setattr(search, "cache_get", _cache_get)
    monkeypatch.setattr(search, "rate_limit", _limit)

    with pytest.raises(search.SearchRateLimited, match="tenant_search_rate_limited"):
        await search.search_public_web("tenant-a", "best coffee")
    assert keys == ["ai-vis:search:tenant:tenant-a"]


@pytest.mark.asyncio
async def test_search_uses_cache(monkeypatch):
    calls = []

    async def _cache_get(key):
        if key.endswith(":blocked"):
            return None
        return '[{"url": "https://example.com/cached", "title": "Cached", "snippet": "x"}]'

    monkeypatch.setattr(search, "cache_get", _cache_get)

    async def _allow(*_args, **_kwargs):
        return True

    monkeypatch.setattr(search, "rate_limit", _allow)

    async def _fetch(*args, **kwargs):
        calls.append(args)
        raise AssertionError("cache hit must not fetch")

    monkeypatch.setattr(search, "fetch_pinned_bytes", _fetch)
    results = await search.search_public_web("tenant", "best coffee")
    assert results[0].url == "https://example.com/cached"
    assert calls == []

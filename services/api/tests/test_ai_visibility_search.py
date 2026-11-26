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


def test_build_query_uses_entity_and_locality():
    query = search.build_query(
        "What are the best options near Sayvors Company Branch-Makkah?",
        {"name": "Sayvors Company Branch-Makkah", "address": "Makkah"},
    )
    assert query.startswith("Sayvors Company Branch-Makkah")
    assert "Makkah" in query
    assert "best options" not in query.casefold()


def test_build_query_does_not_repeat_the_entity():
    query = search.build_query(
        "Is Sayvors Company Branch-Makkah recommended by reliable sources?",
        {"name": "Sayvors Company Branch-Makkah"},
    )
    assert query.casefold().count("sayvors") == 1


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
async def test_discover_public_profiles_marks_found_and_missing(monkeypatch):
    async def _search(_tenant, query):
        if "facebook.com" in query:
            return [
                search.SearchResult(
                    url="https://www.facebook.com/sayvors",
                    title="Sayvors Company",
                    snippet="Makkah branch",
                )
            ]
        return []

    monkeypatch.setattr(search, "search_public_web", _search)
    rows = await search.discover_public_profiles(
        "tenant-1", "Sayvors Company Makkah", "Sayvors Company Branch-Makkah"
    )
    by_platform = {row["platform"]: row for row in rows}
    assert by_platform["Facebook"]["status"] == "found"
    assert by_platform["Instagram"]["status"] == "not_found"


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


DDG_HTML = b"""<html><body>
<div class="result__body">
<h2 class="result__title">
<a rel="nofollow" class="result__a"
   href="//duckduckgo.com/l/?uddg=https%3A%2F%2Facme.example%2Fcoffee&amp;rut=abc">
Acme <b>Coffee</b></a></h2>
<a class="result__snippet"
   href="//duckduckgo.com/l/?uddg=https%3A%2F%2Facme.example%2Fcoffee">
Fresh <b>coffee</b> near Malqa.</a>
</div>
<div class="result__body">
<h2 class="result__title">
<a class="result__a" href="https://rival.example/">Duplicate Acme</a></h2>
</div>
</body></html>"""


def test_parse_ddg_html_unwraps_redirector_and_pairs_snippets():
    rows = search.parse_ddg_html(DDG_HTML)
    assert [row.url for row in rows] == [
        "https://acme.example/coffee",
        "https://rival.example/",
    ]
    assert rows[0].title == "Acme Coffee"
    assert rows[0].snippet == "Fresh coffee near Malqa."
    assert rows[1].snippet == ""


def test_build_queries_deep_adds_domain_shape():
    branch = {
        "name": "MenteE",
        "address": "Mingora",
        "website": "https://menteeai.org/",
    }
    deep = search.build_queries("Who recommends MenteE?", branch, "deep")
    assert deep[0].startswith("MenteE")
    assert deep[1] == "menteeai.org"
    assert deep[2] == "site:menteeai.org"
    assert search.build_queries("Who recommends MenteE?", branch, "quick") == [
        deep[0]
    ]


@pytest.mark.asyncio
async def test_search_many_ranks_brand_candidates_above_noise(monkeypatch):
    async def _noise(_tenant, query, **_kwargs):
        if query.startswith("site:") or query.endswith(".example"):
            return [
                search.SearchResult(
                    url="https://acme.example/products", title="Acme products", snippet=""
                )
            ]
        return [
            search.SearchResult(
                url="https://en.wikipedia.org/wiki/Malqa", title="Malqa - Wikipedia", snippet=""
            )
        ]

    monkeypatch.setattr(search, "search_public_web", _noise)
    rows = await search.search_many(
        "tenant",
        ["Acme Malqa", "acme.example", "site:acme.example"],
        distinctive={"acme"},
    )
    assert rows[0].url == "https://acme.example/products"


@pytest.mark.asyncio
async def test_bing_filler_triggers_duckduckgo_backup(monkeypatch):
    async def _cache_get(_key):
        return None

    async def _cache_set(*_args, **_kwargs):
        return None

    async def _allow(*_args, **_kwargs):
        return True

    async def _bing(_query):
        return [
            search.SearchResult(
                url="https://translate.google.com/?hl=ar",
                title="Google Translate",
                snippet="",
            )
        ]

    async def _ddg(_query):
        return [
            search.SearchResult(
                url="https://acme.example/coffee",
                title="Acme Coffee",
                snippet="Fresh coffee.",
            )
        ]

    monkeypatch.setattr(search, "cache_get", _cache_get)
    monkeypatch.setattr(search, "cache_set", _cache_set)
    monkeypatch.setattr(search, "rate_limit", _allow)
    monkeypatch.setattr(search, "_fetch_results", _bing)
    monkeypatch.setattr(search, "_fetch_ddg_results", _ddg)

    providers: list[str] = []
    rows = await search.search_public_web(
        "tenant", "Acme Malqa", distinctive={"acme"}, providers=providers
    )
    assert rows[0].url == "https://acme.example/coffee"
    assert providers == [search.BING_PROVIDER_LABEL, search.DDG_PROVIDER_LABEL]


@pytest.mark.asyncio
async def test_matching_bing_results_never_consult_duckduckgo(monkeypatch):
    async def _cache_get(_key):
        return None

    async def _cache_set(*_args, **_kwargs):
        return None

    async def _allow(*_args, **_kwargs):
        return True

    async def _bing(_query):
        return [
            search.SearchResult(
                url="https://acme.example/coffee", title="Acme Coffee", snippet=""
            )
        ]

    async def _ddg(_query):
        raise AssertionError("duckduckgo must not be consulted")

    monkeypatch.setattr(search, "cache_get", _cache_get)
    monkeypatch.setattr(search, "cache_set", _cache_set)
    monkeypatch.setattr(search, "rate_limit", _allow)
    monkeypatch.setattr(search, "_fetch_results", _bing)
    monkeypatch.setattr(search, "_fetch_ddg_results", _ddg)

    providers: list[str] = []
    rows = await search.search_public_web(
        "tenant", "Acme", distinctive={"acme"}, providers=providers
    )
    assert len(rows) == 1
    assert providers == [search.BING_PROVIDER_LABEL]


@pytest.mark.asyncio
async def test_duckduckgo_answers_while_bing_is_blocked(monkeypatch):
    async def _cache_get(key):
        return "1" if "bing:blocked" in key else None

    async def _cache_set(*_args, **_kwargs):
        return None

    async def _allow(*_args, **_kwargs):
        return True

    async def _ddg(_query):
        return [
            search.SearchResult(
                url="https://acme.example/coffee", title="Acme Coffee", snippet=""
            )
        ]

    monkeypatch.setattr(search, "cache_get", _cache_get)
    monkeypatch.setattr(search, "cache_set", _cache_set)
    monkeypatch.setattr(search, "rate_limit", _allow)
    monkeypatch.setattr(search, "_fetch_ddg_results", _ddg)

    providers: list[str] = []
    rows = await search.search_public_web("tenant", "acme coffee", providers=providers)
    assert rows[0].url == "https://acme.example/coffee"
    assert providers == [search.DDG_PROVIDER_LABEL]


@pytest.mark.asyncio
async def test_search_fails_when_both_providers_are_down(monkeypatch):
    async def _cache_get(_key):
        return None

    async def _allow(*_args, **_kwargs):
        return True

    async def _bing(_query):
        raise RuntimeError("boom")

    async def _ddg(_query):
        raise RuntimeError("boom")

    monkeypatch.setattr(search, "cache_get", _cache_get)
    monkeypatch.setattr(search, "rate_limit", _allow)
    monkeypatch.setattr(search, "_fetch_results", _bing)
    monkeypatch.setattr(search, "_fetch_ddg_results", _ddg)

    with pytest.raises(search.SearchUnavailable):
        await search.search_public_web("tenant", "acme coffee")


@pytest.mark.asyncio
async def test_ddg_anomaly_engages_its_own_cooldown(monkeypatch):
    stored: dict[str, str] = {}

    async def _cache_get(_key):
        return None

    async def _cache_set(key, _value, **_kwargs):
        stored[key] = "1"

    async def _allow(*_args, **_kwargs):
        return True

    async def _bing(_query):
        raise RuntimeError("bing down")

    async def _ddg(_query):
        raise search.SearchBlocked("ddg_anomaly")

    monkeypatch.setattr(search, "cache_get", _cache_get)
    monkeypatch.setattr(search, "cache_set", _cache_set)
    monkeypatch.setattr(search, "rate_limit", _allow)
    monkeypatch.setattr(search, "_fetch_results", _bing)
    monkeypatch.setattr(search, "_fetch_ddg_results", _ddg)

    with pytest.raises(search.SearchUnavailable):
        await search.search_public_web("tenant", "acme coffee")
    assert stored[search.DDG_BLOCK_KEY] == "1"


def test_ddg_anomaly_page_is_not_parsed_as_results():
    body = (
        b"<html><div class='anomaly-modal__box'>prove you are human</div></html>"
    )
    assert search.parse_ddg_html(body) == []
    assert search._is_ddg_anomaly(body)

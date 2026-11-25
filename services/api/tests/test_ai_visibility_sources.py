"""SSRF-safe, bounded source snapshots for grounded research."""
import hashlib
from urllib.parse import urlsplit

import pytest

from app.modules.ai_visibility import sources


@pytest.fixture(autouse=True)
def _allow_domain_rates(monkeypatch):
    async def _allow(*_args, **_kwargs):
        return True

    monkeypatch.setattr(sources, "rate_limit", _allow)


def _result(url, title="Example"):
    from app.modules.ai_visibility.search import SearchResult

    return SearchResult(url=url, title=title, snippet="snippet")


def test_select_sources_deduplicates_and_caps_domains():
    rows = [
        _result("https://a.example/1"),
        _result("https://a.example/2"),
        _result("https://a.example/3"),
        _result("https://b.example/1"),
        _result("https://c.example/1"),
        _result("https://d.example/1"),
    ]
    selected = sources.select_sources(rows)
    assert len(selected) == 5
    assert sum(urlsplit(row.url).hostname == "a.example" for row in selected) == 2


@pytest.mark.asyncio
async def test_fetch_source_rejects_private_target(monkeypatch):
    def _blocked(*args, **kwargs):
        raise ValueError("private address")

    monkeypatch.setattr(sources, "fetch_pinned_media", _blocked)
    row = await sources.fetch_source("run-1", 0, _result("http://127.0.0.1"))
    assert row.fetch_error
    assert row.excerpt is None


@pytest.mark.asyncio
async def test_fetch_source_extracts_bounded_text(monkeypatch):
    monkeypatch.setattr(
        sources,
        "fetch_pinned_media",
        lambda *a, **k: (
            b"<html><body><p>Evidence text</p></body></html>",
            "text/html",
        ),
    )
    monkeypatch.setattr(
        sources.trafilatura, "extract", lambda *a, **k: "Evidence text"
    )
    row = await sources.fetch_source(
        "run-1", 0, _result("https://example.com/page")
    )
    assert row.excerpt == "Evidence text"
    assert row.content_hash == hashlib.sha256(b"Evidence text").hexdigest()
    assert row.canonical_url == "https://example.com/page"

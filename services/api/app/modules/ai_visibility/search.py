"""Bounded public web search with cache, rate limits, and no API key."""
from __future__ import annotations

import asyncio
import json
import re
from dataclasses import asdict, dataclass
from html import unescape
from html.parser import HTMLParser
from urllib.parse import quote_plus
from xml.etree import ElementTree

from ...core.pinned_http import UnsafeUrlError, assert_public_http_url, fetch_pinned_bytes
from ..auth.rate_limit import rate_limit
from ..redis.service import cache_get, cache_set

SEARCH_CACHE_SECONDS = 6 * 60 * 60
SEARCH_RATE_LIMIT = 30
SEARCH_RATE_WINDOW_SECONDS = 60
SEARCH_BLOCK_COOLDOWN_SECONDS = 15 * 60
MAX_SEARCH_RESULTS = 10
MAX_SEARCH_BYTES = 1024 * 1024
SEARCH_TIMEOUT_SECONDS = 10.0
BING_RSS_URL = "https://www.bing.com/search?format=rss&q={query}"
BING_HTML_URL = "https://www.bing.com/search?q={query}"


@dataclass(frozen=True)
class SearchResult:
    url: str
    title: str
    snippet: str


class SearchRateLimited(RuntimeError):
    pass


class SearchUnavailable(RuntimeError):
    pass


class SearchBlocked(RuntimeError):
    pass


def normalize_query(query: str) -> str:
    return " ".join(query.casefold().split())


def parse_bing_rss(body: bytes) -> list[SearchResult]:
    root = ElementTree.fromstring(body)
    rows: list[SearchResult] = []
    seen: set[str] = set()
    for item in root.findall(".//item"):
        title = unescape((item.findtext("title") or "").strip())
        link = unescape((item.findtext("link") or "").strip())
        if not link or link in seen:
            continue
        seen.add(link)
        description = re.sub(r"<[^>]+>", " ", item.findtext("description") or "")
        rows.append(SearchResult(link, title, unescape(description).strip()))
        if len(rows) == MAX_SEARCH_RESULTS:
            break
    return rows


def safe_results(rows: list[SearchResult]) -> list[SearchResult]:
    seen: set[str] = set()
    out: list[SearchResult] = []
    for row in rows:
        try:
            url = assert_public_http_url(row.url)
        except (UnsafeUrlError, ValueError):
            continue
        if url in seen:
            continue
        seen.add(url)
        out.append(SearchResult(url, row.title[:500], row.snippet[:2000]))
        if len(out) == MAX_SEARCH_RESULTS:
            break
    return out


class _BingHtmlParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows: list[SearchResult] = []
        self._in_algo = False
        self._in_h2 = False
        self._in_link = False
        self._title: list[str] = []
        self._url = ""
        self._snippet: list[str] = []
        self._in_snippet = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get("class", "").split()
        if tag == "li" and "b_algo" in classes:
            self._in_algo = True
            self._title, self._snippet = [], []
            self._url = ""
        elif self._in_algo and tag == "h2":
            self._in_h2 = True
        elif self._in_h2 and tag == "a" and attrs.get("href"):
            self._in_link = True
            self._url = attrs["href"]
        elif self._in_algo and tag == "p":
            self._in_snippet = True

    def handle_data(self, data):
        if self._in_link:
            self._title.append(data)
        elif self._in_snippet:
            self._snippet.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._in_link:
            self._in_link = False
        elif tag == "h2" and self._in_h2:
            self._in_h2 = False
        elif tag == "p" and self._in_snippet:
            self._in_snippet = False
        elif tag == "li" and self._in_algo:
            self._in_algo = False
            if self._url:
                self.rows.append(
                    SearchResult(
                        self._url,
                        "".join(self._title).strip(),
                        "".join(self._snippet).strip(),
                    )
                )


def parse_bing_html(body: bytes) -> list[SearchResult]:
    parser = _BingHtmlParser()
    parser.feed(body.decode("utf-8", errors="ignore"))
    return parser.rows[:MAX_SEARCH_RESULTS]


async def _fetch_results(query: str) -> list[SearchResult]:
    encoded = quote_plus(query)
    try:
        body = await asyncio.to_thread(
            fetch_pinned_bytes,
            BING_RSS_URL.format(query=encoded),
            timeout=SEARCH_TIMEOUT_SECONDS,
            max_bytes=MAX_SEARCH_BYTES,
            user_agent="SayvorsResearchBot/1.0",
        )
        return safe_results(parse_bing_rss(body))
    except Exception:
        try:
            body = await asyncio.to_thread(
                fetch_pinned_bytes,
                BING_HTML_URL.format(query=encoded),
                timeout=SEARCH_TIMEOUT_SECONDS,
                max_bytes=MAX_SEARCH_BYTES,
                user_agent="SayvorsResearchBot/1.0",
            )
        except Exception as exc:
            message = str(exc).casefold()
            if "429" in message or "captcha" in message:
                raise SearchBlocked("search_blocked") from exc
            raise
        rows = safe_results(parse_bing_html(body))
        if not rows:
            raise SearchBlocked("search_blocked")
        return rows


async def search_public_web(tenant_id: str, query: str) -> list[SearchResult]:
    normalized = normalize_query(query)
    if not normalized:
        return []
    cache_key = f"ai-vis:search:{tenant_id}:{normalized}"
    block_key = "ai-vis:search:bing:blocked"
    if await cache_get(block_key):
        raise SearchUnavailable("search_blocked")
    cached_raw = await cache_get(cache_key)
    if cached_raw is not None:
        try:
            cached = json.loads(cached_raw)
        except (TypeError, ValueError):
            cached = []
        return safe_results([SearchResult(**row) for row in cached])
    if not await rate_limit(
        "ai-vis:search:bing",
        SEARCH_RATE_LIMIT,
        SEARCH_RATE_WINDOW_SECONDS,
        fail_closed=True,
    ):
        raise SearchRateLimited("search_rate_limited")
    try:
        rows = await _fetch_results(normalized)
    except SearchBlocked as exc:
        await cache_set(block_key, "1", ttl=SEARCH_BLOCK_COOLDOWN_SECONDS)
        raise SearchUnavailable("search_blocked") from exc
    except Exception as exc:
        raise SearchUnavailable("search_unavailable") from exc
    await cache_set(
        cache_key,
        json.dumps([asdict(row) for row in rows]),
        ttl=SEARCH_CACHE_SECONDS,
    )
    return rows

"""Bounded public web search with cache, rate limits, and no API key."""
from __future__ import annotations

import asyncio
import json
import re
from dataclasses import asdict, dataclass
from html import unescape
from html.parser import HTMLParser
from urllib.parse import parse_qs, quote_plus, urlsplit
from xml.etree import ElementTree

from ...core.pinned_http import UnsafeUrlError, assert_public_http_url, fetch_pinned_bytes
from ..auth.rate_limit import rate_limit
from ..redis.service import cache_get, cache_set

SEARCH_CACHE_SECONDS = 6 * 60 * 60
SEARCH_RATE_LIMIT = 30
TENANT_SEARCH_RATE_LIMIT = 10
SEARCH_RATE_WINDOW_SECONDS = 60
SEARCH_BLOCK_COOLDOWN_SECONDS = 15 * 60
MAX_SEARCH_RESULTS = 10
DEEP_MAX_CANDIDATES = 20
MAX_SEARCH_BYTES = 1024 * 1024
SEARCH_TIMEOUT_SECONDS = 10.0
BING_RSS_URL = "https://www.bing.com/search?format=rss&q={query}"
BING_HTML_URL = "https://www.bing.com/search?q={query}"
DDG_HTML_URL = "https://html.duckduckgo.com/html/?q={query}"
BING_PROVIDER_LABEL = "Bing public web"
DDG_PROVIDER_LABEL = "DuckDuckGo public web"
DDG_BLOCK_KEY = "ai-vis:search:ddg:blocked"
# DDG's HTML endpoint serves an anomaly page to unknown bots; a normal
# browser UA keeps the parseable result layout.
DDG_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


@dataclass(frozen=True)
class SearchResult:
    url: str
    title: str
    snippet: str


PUBLIC_PLATFORM_DOMAINS = (
    ("Facebook", "facebook.com", "https://www.facebook.com/pages/create"),
    ("Instagram", "instagram.com", "https://business.instagram.com/"),
    ("TikTok", "tiktok.com", "https://www.tiktok.com/business/"),
    ("LinkedIn", "linkedin.com", "https://www.linkedin.com/company/setup/new/"),
    ("YouTube", "youtube.com", "https://www.youtube.com/creators/"),
)


async def discover_public_profiles(
    tenant_id: str, query: str, branch_name: str
) -> list[dict]:
    """Find public social profiles through the same public search index.

    Private accounts are never accessed. A platform with no relevant public
    result is reported as not found, not as proof that no account exists.
    """
    tokens = [
        token
        for token in re.findall(r"[a-z0-9\u0600-\u06ff]{4,}", branch_name.casefold())
        if token not in {"company", "branch", "business", "location"}
    ]
    profiles: list[dict] = []
    for name, domain, setup_url in PUBLIC_PLATFORM_DOMAINS:
        platform_query = f"site:{domain} {query}"[:300]
        try:
            rows = await search_public_web(tenant_id, platform_query)
            found = next(
                (
                    row
                    for row in rows
                    if domain in (urlsplit(row.url).hostname or "")
                    and (
                        not tokens
                        or any(
                            token in f"{row.title} {row.snippet}".casefold()
                            for token in tokens
                        )
                    )
                ),
                None,
            )
            profiles.append(
                {
                    "platform": name,
                    "status": "found" if found else "not_found",
                    "url": found.url if found else None,
                    "query": platform_query,
                    "setup_url": setup_url,
                }
            )
        except (SearchRateLimited, SearchUnavailable):
            profiles.append(
                {
                    "platform": name,
                    "status": "unknown",
                    "url": None,
                    "query": platform_query,
                    "setup_url": setup_url,
                }
            )
    return profiles


class SearchRateLimited(RuntimeError):
    pass


class TenantSearchRateLimited(SearchRateLimited):
    pass


class SearchUnavailable(RuntimeError):
    pass


class SearchBlocked(RuntimeError):
    pass


def normalize_query(query: str) -> str:
    return " ".join(query.casefold().split())


QUESTION_WORDS = re.compile(
    r"\b(what|which|who|are|is|the|best|top|options?|near|recommend(?:ed)?|"
    r"reliable|sources?|for|in|at|by|with|about|compare|versus|vs)\b",
    re.I,
)


def build_query(prompt: str, branch: dict) -> str:
    """Turn a natural question into a local-entity search query.

    Raw questions like "What are the best options near Acme?" make Bing
    return generic YouTube/help pages. A named entity plus locality produces
    pages about the business instead.
    """
    name = " ".join(str(branch.get("name") or "").split())
    locality = " ".join(
        str(branch.get("address") or branch.get("locality") or "").split()
    )
    remainder = " ".join(QUESTION_WORDS.sub(" ", prompt).split())
    remainder = re.sub(r"[?.,!]+", " ", remainder)
    remainder = " ".join(remainder.split())
    # The branch name is already the leading phrase; do not repeat it because
    # a model/user question often contains the name with punctuation.
    if name and name.casefold() in remainder.casefold():
        remainder = ""
    parts = [part for part in (name, remainder, locality) if part]
    if not parts:
        return normalize_query(prompt)
    return " ".join(parts)[:300]


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


_DDG_ANCHOR_RE = re.compile(
    r'<a\b(?P<attrs>[^>]*class="[^"]*\bresult__a\b[^"]*"[^>]*)>(?P<title>.*?)</a>',
    re.S | re.I,
)
_DDG_SNIPPET_RE = re.compile(
    r'<a\b[^>]*class="[^"]*\bresult__snippet\b[^"]*"[^>]*>(?P<snippet>.*?)</a>',
    re.S | re.I,
)
_HREF_RE = re.compile(r'href="(?P<href>[^"]+)"', re.I)


def _unwrap_ddg_link(href: str) -> str:
    """DDG routes result clicks through its own redirector; recover the target.

    The wrapped link is the only place the real URL appears, so unwrapping is
    required before the SSRF check and dedup can work on the actual origin.
    """
    if href.startswith("//"):
        href = f"https:{href}"
    parts = urlsplit(href)
    if parts.netloc.casefold().endswith("duckduckgo.com") and parts.path.startswith("/l/"):
        target = parse_qs(parts.query).get("uddg", [""])[0]
        return target or href
    return href


def _flatten_html_fragment(value: str) -> str:
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", value)).split())


def parse_ddg_html(body: bytes) -> list[SearchResult]:
    """Parse the DuckDuckGo HTML endpoint into bounded, de-duplicated results."""
    text = body.decode("utf-8", "replace")
    snippets = [
        _flatten_html_fragment(match.group("snippet"))
        for match in _DDG_SNIPPET_RE.finditer(text)
    ]
    rows: list[SearchResult] = []
    seen: set[str] = set()
    for index, match in enumerate(_DDG_ANCHOR_RE.finditer(text)):
        href_match = _HREF_RE.search(match.group("attrs"))
        if not href_match:
            continue
        url = _unwrap_ddg_link(unescape(href_match.group("href")))
        if not url or url in seen:
            continue
        seen.add(url)
        rows.append(
            SearchResult(
                url,
                _flatten_html_fragment(match.group("title")),
                snippets[index] if index < len(snippets) else "",
            )
        )
        if len(rows) == MAX_SEARCH_RESULTS:
            break
    return rows


async def _fetch_ddg_results(query: str) -> list[SearchResult]:
    body = await asyncio.to_thread(
        fetch_pinned_bytes,
        DDG_HTML_URL.format(query=quote_plus(query)),
        timeout=SEARCH_TIMEOUT_SECONDS,
        max_bytes=MAX_SEARCH_BYTES,
        user_agent=DDG_USER_AGENT,
    )
    if _is_ddg_anomaly(body):
        raise SearchBlocked("ddg_anomaly")
    return safe_results(parse_ddg_html(body))


def _is_ddg_anomaly(body: bytes) -> bool:
    """Detect DDG's anti-bot interstitial before treating it as an answer."""
    lowered = body.lower()
    return b"anomaly-modal" in lowered or b"/anomaly.js" in lowered


def _row_matches_tokens(row: SearchResult, tokens: set[str]) -> bool:
    text = f"{row.url} {row.title} {row.snippet}".casefold()
    return any(token in text for token in tokens)


def _rows_match_tokens(rows: list[SearchResult], tokens: set[str]) -> bool:
    """True when at least one result mentions a distinctive branch token."""
    return any(_row_matches_tokens(row, tokens) for row in rows)


def _merge_rows(
    primary: list[SearchResult], secondary: list[SearchResult]
) -> list[SearchResult]:
    """Concatenate two providers' candidates, primary first, deduplicated."""
    out: list[SearchResult] = []
    seen: set[str] = set()
    for row in primary + secondary:
        key = canonical_url(row.url)
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
        if len(out) >= MAX_SEARCH_RESULTS:
            break
    return out


async def _duckduckgo(
    tenant_id: str, query: str, providers: list[str] | None
) -> list[SearchResult]:
    """Secondary provider; any failure here degrades to Bing-only results."""
    if await cache_get(DDG_BLOCK_KEY):
        return []
    if not await rate_limit(
        "ai-vis:search:ddg",
        SEARCH_RATE_LIMIT,
        SEARCH_RATE_WINDOW_SECONDS,
        fail_closed=False,
    ):
        return []
    try:
        rows = await _fetch_ddg_results(query)
    except SearchBlocked:
        # DDG flags our datacenter as botnet traffic under rapid use; sit out
        # its cooldown window instead of escalating the block with retries.
        await cache_set(DDG_BLOCK_KEY, "1", ttl=SEARCH_BLOCK_COOLDOWN_SECONDS)
        return []
    except Exception:
        return []
    if rows and providers is not None:
        providers.append(DDG_PROVIDER_LABEL)
    return rows


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


def _branch_domain(branch: dict) -> str:
    """Extract a registrable host from the branch's recorded website.

    Brand-centric businesses are covered by pages on their own domain, which
    address-shaped queries never surface. Empty when no usable website exists.
    """
    website = str(branch.get("website") or "").strip()
    if not website:
        return ""
    candidate = website if "//" in website else f"https://{website}"
    host = urlsplit(candidate).netloc.casefold().removeprefix("www.")
    return host if "." in host and " " not in host else ""


def build_queries(prompt: str, branch: dict, depth: str) -> list[str]:
    base = build_query(prompt, branch)
    if depth != "deep":
        return [base]
    # Own-domain queries come right after the base query: they carry the most
    # signal for brand-centric businesses, and the candidate cap must not be
    # filled by address-shaped noise before they are searched.
    queries = [base]
    domain = _branch_domain(branch)
    if domain:
        queries.extend([domain, f"site:{domain}"])
    queries.extend([f"{base} reviews", f"{base} news"])
    return queries


async def search_many(
    tenant_id: str,
    queries: list[str],
    *,
    max_results: int = DEEP_MAX_CANDIDATES,
    distinctive: set[str] | None = None,
    providers: list[str] | None = None,
) -> list[SearchResult]:
    """Aggregate every query's candidates, deduplicated and ranked for depth.

    All queries are collected before the cap is applied: the address-shaped
    base query tends to fill with locality noise, and the brand/own-domain
    queries that carry real coverage must never be cut by it. When
    ``distinctive`` tokens exist, brand-mentioning candidates rank first so
    the fetch budget reads the pages that are about this branch.
    """
    rows: list[SearchResult] = []
    seen: set[str] = set()
    for query in queries:
        for row in await search_public_web(
            tenant_id, query, distinctive=distinctive, providers=providers
        ):
            key = canonical_url(row.url)
            if key in seen:
                continue
            seen.add(key)
            rows.append(row)
    if distinctive:
        # Stable sort: brand-mentioning rows lead, otherwise order preserved.
        rows.sort(key=lambda row: 0 if _row_matches_tokens(row, distinctive) else 1)
    return rows[:max_results]


def canonical_url(url: str) -> str:
    from urllib.parse import urlsplit, urlunsplit

    parts = urlsplit(url.strip())
    return urlunsplit(
        (parts.scheme.casefold(), parts.netloc.casefold(), parts.path or "/", parts.query, "")
    )


async def search_public_web(
    tenant_id: str,
    query: str,
    *,
    distinctive: set[str] | None = None,
    providers: list[str] | None = None,
) -> list[SearchResult]:
    """Keyless public-web search: Bing first, DuckDuckGo as backup.

    Bing's keyless endpoints answer from a heavily regionalized slice of its
    index and, when they have nothing for a query, return generic filler
    pages (translate/help/social roots) instead of an honest empty result.
    ``distinctive`` carries the branch's non-locality name tokens; if no Bing
    candidate mentions one — or Bing fails outright — DuckDuckGo is queried
    and its candidates lead, so real coverage of brand-centric businesses
    survives the downstream relevance gate. ``providers`` collects the
    provider labels actually used for honest provenance.
    """
    normalized = normalize_query(query)
    if not normalized:
        return []
    cache_key = f"ai-vis:search:{tenant_id}:{normalized}"
    labels_key = f"ai-vis:search:providers:{tenant_id}:{normalized}"
    block_key = "ai-vis:search:bing:blocked"
    cached_raw = await cache_get(cache_key)
    if cached_raw is not None:
        try:
            cached = json.loads(cached_raw)
        except (TypeError, ValueError):
            cached = None
        if isinstance(cached, list):
            rows = safe_results([SearchResult(**row) for row in cached])
            if providers is not None and rows:
                labels = [BING_PROVIDER_LABEL]
                labels_raw = await cache_get(labels_key)
                try:
                    loaded = json.loads(labels_raw) if labels_raw else None
                except (TypeError, ValueError):
                    loaded = None
                if isinstance(loaded, list):
                    labels = [x for x in loaded if isinstance(x, str)] or labels
                providers.extend(labels)
            return rows
    if not await rate_limit(
        f"ai-vis:search:tenant:{tenant_id}",
        TENANT_SEARCH_RATE_LIMIT,
        SEARCH_RATE_WINDOW_SECONDS,
        fail_closed=True,
    ):
        raise TenantSearchRateLimited("tenant_search_rate_limited")
    bing_error: str | None = None
    rows: list[SearchResult] = []
    if await cache_get(block_key):
        bing_error = "search_blocked"
    else:
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
            bing_error = str(exc)
        except TenantSearchRateLimited:
            raise
        except SearchUnavailable:
            raise
        except Exception:
            bing_error = "search_unavailable"
    if bing_error is None and rows and providers is not None:
        providers.append(BING_PROVIDER_LABEL)
    needs_backup = bool(bing_error) or bool(
        distinctive and not _rows_match_tokens(rows, distinctive)
    )
    if needs_backup:
        ddg_rows = await _duckduckgo(tenant_id, normalized, providers)
        if ddg_rows or not bing_error:
            rows = _merge_rows(ddg_rows, rows) if ddg_rows else rows
        if bing_error and not rows:
            raise SearchUnavailable(bing_error)
    await cache_set(
        cache_key,
        json.dumps([asdict(row) for row in rows]),
        ttl=SEARCH_CACHE_SECONDS,
    )
    if providers:
        await cache_set(
            labels_key,
            json.dumps(list(dict.fromkeys(providers))),
            ttl=SEARCH_CACHE_SECONDS,
        )
    return rows

"""Production crawler core (§31 Phase 1) — replaces the naive _crawl_sync.

Builds on the pinned HTTP layer (SSRF guard + DNS pinning on every redirect
hop) and adds the politeness/sync machinery the one-shot scraper lacked:

- robots.txt compliance (fetched through the pinned fetcher, cached per host,
  with crawl-delay respected and capped)
- per-domain rate limiting (token-bucket style minimum interval)
- per-domain circuit breaker (repeated failures pause a site for a cooldown)
- conditional GET with ETag / Last-Modified (304 => cheap "unchanged")
- sitemap-first discovery (robots sitemap: lines, sitemap index, /sitemap.xml)
  with same-origin BFS fallback
- URL normalization (fragments, utm_* tracking params, default ports)
- trafilatura markdown extraction (canonical, human-readable AND chunk-ready)

Everything here runs in a worker thread (see rag/jobs.py) because the pinned
HTTP layer is synchronous; the module itself has no global mutable state so
tests can run it directly.
"""
from __future__ import annotations

import logging
import re
import time
import urllib.robotparser
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from html.parser import HTMLParser
from typing import Callable
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from ...core.http import assert_public_http_url
from ...core.pinned_http import fetch_pinned_conditional

logger = logging.getLogger(__name__)

USER_AGENT = "SayvorsBot/1.0"

# Politeness bounds. The report targets ~17 site-checks/min at 1000 sites;
# per-domain 1 concurrent with 2-10s between requests is the safe envelope.
DEFAULT_MIN_REQUEST_INTERVAL_SECONDS = 2.0
MAX_REQUEST_INTERVAL_SECONDS = 10.0
ROBOTS_CRAWL_DELAY_CAP_SECONDS = 10.0

# Circuit breaker: three consecutive failures pause the domain for 15 minutes.
BREAKER_FAIL_THRESHOLD = 3
BREAKER_COOLDOWN_SECONDS = 15 * 60

MAX_FETCH_BYTES = 5 * 1024 * 1024
MAX_SITEMAP_URLS = 2000
TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
                   "gclid", "fbclid", "yclid", "igshid", "mc_cid", "mc_eid"}

_HTML_CONTENT_TYPES = {"text/html", "application/xhtml+xml"}
_SITEMAP_LINK_RE = re.compile(r"<loc>\s*(.*?)\s*</loc>", re.IGNORECASE)


@dataclass
class CrawlResult:
    """Outcome for one discovered page."""

    url: str
    status: str  # crawled | unchanged | failed
    title: str | None = None
    markdown: str = ""
    word_count: int = 0
    lang: str | None = None
    etag: str | None = None
    last_modified: str | None = None
    content_hash: str | None = None
    error: str | None = None


@dataclass
class _DomainGate:
    """Per-domain politeness + breaker state."""

    min_interval: float = DEFAULT_MIN_REQUEST_INTERVAL_SECONDS
    _last_request_at: float = 0.0
    _failures: int = 0
    _blocked_until: float = 0.0

    def wait_if_needed(self) -> None:
        if self._blocked_until > time.monotonic():
            raise _DomainBlocked(self._blocked_until)
        elapsed = time.monotonic() - self._last_request_at
        wait = self.min_interval - elapsed
        if wait > 0:
            time.sleep(wait)

    def note_request(self) -> None:
        self._last_request_at = time.monotonic()

    def note_success(self) -> None:
        self._failures = 0

    def note_failure(self) -> None:
        self._failures += 1
        if self._failures >= BREAKER_FAIL_THRESHOLD:
            self._blocked_until = time.monotonic() + BREAKER_COOLDOWN_SECONDS
            self._failures = 0

    @property
    def blocked(self) -> bool:
        return self._blocked_until > time.monotonic()


class _DomainBlocked(Exception):
    pass


def normalize_url(url: str, base: str | None = None) -> str:
    """Normalize a URL for dedup: strip fragments, tracking params, defaults.

    Host is lowercased; the path keeps case (servers are case-sensitive).
    A bare host yields ``https://host/`` so crawling and dedup agree.
    """
    if base:
        url = urljoin(base, url)
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError(f"not an http(s) URL: {url!r}")
    host = parsed.hostname.lower()
    try:
        port = parsed.port
    except ValueError:
        port = None
    # Drop default ports so https://host/ and https://host:443/ dedup.
    default_port = 443 if parsed.scheme == "https" else 80
    netloc = host if port is None or port == default_port else f"{host}:{port}"
    path = parsed.path or "/"
    query = ""
    if parsed.query:
        kept = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True)
                if k.lower() not in TRACKING_PARAMS]
        query = urlencode(kept)
    return urlunparse((parsed.scheme, netloc, path, "", query, ""))


def same_origin(a: str, b: str) -> bool:
    return urlparse(a).netloc == urlparse(b).netloc


def _normalize_selected_urls(
    start_url: str, urls: list[str], max_pages: int
) -> list[str]:
    """Normalize + same-origin-filter an explicit URL selection."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in urls:
        if len(out) >= max_pages:
            break
        try:
            url = normalize_url(raw, start_url)
        except ValueError:
            continue
        if url in seen or not same_origin(start_url, url):
            continue
        seen.add(url)
        out.append(url)
    return out


class RobotsRules:
    """Cached robots.txt rules for one host (fetched via pinned HTTP)."""

    def __init__(self, base_url: str, fetcher: Callable | None = None):
        self._netloc = urlparse(base_url).netloc
        self._parser = urllib.robotparser.RobotFileParser()
        self._crawl_delay: float | None = None
        self._has_rules = False
        # The injected fetcher follows the page signature (url, etag=,
        # last_modified=) -> (status, headers, body); adapt it to text here
        # so callers pass the same fetcher everywhere.
        self._fetcher = _robots_fetcher(fetcher) if fetcher is not None else None
        self._load(base_url)

    def _load(self, base_url: str) -> None:
        robots_url = urljoin(base_url, "/robots.txt")
        fetch = self._fetcher or _fetch_robots_text
        try:
            text = fetch(robots_url)
        except Exception as e:  # noqa: BLE001 — robots must never break a crawl
            logger.debug("robots.txt unavailable for %s: %s", self._netloc, e)
            return
        self._parser.parse(text.splitlines())
        self._has_rules = True
        for line in text.splitlines():
            match = re.match(r"^\s*Crawl-delay\s*:\s*([0-9.]+)\s*$", line, re.IGNORECASE)
            if match:
                self._crawl_delay = float(match.group(1))
                break

    def allowed(self, url: str) -> bool:
        if not self._has_rules:
            return True
        try:
            return self._parser.can_fetch(USER_AGENT, url)
        except Exception:
            return True

    @property
    def crawl_delay(self) -> float:
        if self._crawl_delay is None:
            return DEFAULT_MIN_REQUEST_INTERVAL_SECONDS
        return max(DEFAULT_MIN_REQUEST_INTERVAL_SECONDS,
                   min(self._crawl_delay, ROBOTS_CRAWL_DELAY_CAP_SECONDS))


def _fetch_robots_text(url: str) -> str:
    """Robots.txt is fetched through the pinned fetcher (SSRF-safe) but with
    tolerant handling: a 404 or non-HTML response means no rules."""
    status, headers, body = fetch_pinned_conditional(
        url, timeout=15.0, user_agent=USER_AGENT, max_bytes=512 * 1024
    )
    if status != 200:
        return ""
    ctype = headers.get("content-type", "").split(";")[0].strip().lower()
    if ctype and ctype not in _HTML_CONTENT_TYPES and ctype != "text/plain":
        return ""
    return body.decode("utf-8", errors="ignore")


def discover_sitemap_urls(start_url: str, max_urls: int, gate: _DomainGate,
                          robots: RobotsRules, fetcher: Callable | None = None) -> list[str]:
    """Collect URLs from robots sitemap: lines and /sitemap.xml (incl. index).

    Returns normalized URLs, capped at max_urls. A missing sitemap returns []
    so the caller falls back to BFS.
    """
    fetch = fetcher or _conditional_fetch
    candidates: list[str] = []
    if robots._has_rules:
        for sitemap in robots._parser.sitemaps:
            candidates.extend(_flatten_sitemap(sitemap, max_urls, gate, fetch))
            if len(candidates) >= max_urls:
                break
    if not candidates:
        probe = urljoin(start_url, "/sitemap.xml")
        candidates.extend(_flatten_sitemap(probe, max_urls, gate, fetch))
    seen: set[str] = set()
    out: list[str] = []
    for url in candidates:
        try:
            normalized = normalize_url(url, start_url)
        except ValueError:
            continue
        if normalized in seen or not same_origin(start_url, normalized):
            continue
        seen.add(normalized)
        out.append(normalized)
        if len(out) >= max_urls:
            break
    return out


def _flatten_sitemap(sitemap_url: str, max_urls: int, gate: _DomainGate,
                      fetch: Callable) -> list[str]:
    """Fetch one sitemap (or index) and return its <loc> URLs (recursive)."""
    if not (sitemap_url.startswith("http://") or sitemap_url.startswith("https://")):
        return []
    urls: list[str] = []
    try:
        gate.wait_if_needed()
        status, _, body = fetch(sitemap_url)
        gate.note_request()
        if status != 200:
            return []
    except Exception as e:  # noqa: BLE001
        logger.debug("sitemap fetch failed %s: %s", sitemap_url, e)
        return []
    root = None
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        # Not XML — fall back to a loose regex pass (some servers emit
        # unescaped or HTML-wrapped loc entries).
        urls = _SITEMAP_LINK_RE.findall(body.decode("utf-8", errors="ignore"))
    if root is not None:
        tag = root.tag.rsplit("}", 1)[-1]
        if tag == "sitemapindex":
            for loc in root.findall(".//{*}loc"):
                url = (loc.text or "").strip()
                if url:
                    urls.extend(_flatten_sitemap(url, max_urls, gate, fetch))
                if len(urls) >= max_urls:
                    break
        else:
            for loc in root.findall(".//{*}loc"):
                url = (loc.text or "").strip()
                if url:
                    urls.append(url)
                if len(urls) >= max_urls:
                    break
    return [u for u in urls if u][:max_urls]


class _LinkExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            for k, v in attrs:
                if k == "href" and v:
                    self.links.append(v)


def _conditional_fetch(url: str, *, etag: str | None = None,
                       last_modified: str | None = None) -> tuple[int, dict[str, str], bytes]:
    return fetch_pinned_conditional(
        url, timeout=20.0, user_agent=USER_AGENT,
        max_bytes=MAX_FETCH_BYTES, etag=etag, last_modified=last_modified,
    )


def _fetch_page(url: str, gate: _DomainGate, *, etag: str | None = None,
                last_modified: str | None = None,
                fetcher: Callable | None = None) -> tuple[int, dict[str, str], bytes]:
    fetch = fetcher or _conditional_fetch
    gate.wait_if_needed()
    try:
        status, headers, body = fetch(
            url, etag=etag, last_modified=last_modified
        )
    finally:
        gate.note_request()
    return status, headers, body


def _extract_markdown(html: str) -> tuple[str, str | None]:
    """trafilatura -> markdown. Returns (markdown, title)."""
    try:
        import trafilatura
    except ImportError:
        return html.strip(), None
    markdown = trafilatura.extract(
        html,
        output_format="markdown",
        include_links=False,
        include_images=False,
        include_tables=True,
    )
    title = None
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if match:
        title = match.group(1).strip()[:500]
    return (markdown or "").strip(), title


def _discover_bfs(start_url: str, max_urls: int, gate: _DomainGate,
                   robots: RobotsRules, fetcher: Callable | None = None) -> list[str]:
    """Same-origin BFS below start_url, honoring robots and caps."""
    fetch = fetcher or _conditional_fetch
    seen: set[str] = set()
    queue = [start_url]
    discovered: list[str] = []
    while queue and len(discovered) < max_urls:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        try:
            status, headers, body = _fetch_page(url, gate, fetcher=fetcher)
        except Exception as e:  # noqa: BLE001
            logger.debug("bfs fetch failed %s: %s", url, e)
            continue
        if status != 200:
            continue
        ctype = headers.get("content-type", "").split(";")[0].strip().lower()
        if ctype and ctype not in _HTML_CONTENT_TYPES:
            continue
        if not robots.allowed(url):
            continue
        if url not in discovered:
            discovered.append(url)
        parser = _LinkExtractor()
        try:
            parser.feed(body.decode("utf-8", errors="ignore"))
        except Exception:
            continue
        for link in parser.links:
            try:
                full = normalize_url(link, url)
            except ValueError:
                continue
            if same_origin(start_url, full) and full not in seen and robots.allowed(full):
                queue.append(full)
    return discovered


@dataclass
class PageCandidate:
    """A discovered page shown in the pre-crawl selection UI."""

    url: str
    title: str | None = None
    status: str = "discovered"


def _parse_title(html: str) -> str | None:
    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    return match.group(1).strip()[:500] if match else None


def preview_candidates(
    start_url: str,
    scope: str = "subtree",
    max_pages: int = 100,
    fetcher: Callable | None = None,
) -> list[PageCandidate]:
    """Discover candidate pages WITHOUT crawling/storing content.

    This is the interactive selection step: the tenant sees every page the
    crawler would touch, ticks the ones they want, and the chosen subset is
    what a later crawl fetches. Only lightweight HEAD/GET + <title> parsing
    happens here — no trafilatura, no downloads, no DB writes.
    """
    assert_public_http_url(start_url)
    start_url = normalize_url(start_url)

    robots = RobotsRules(start_url, fetcher=fetcher)
    gate = _DomainGate(min_interval=robots.crawl_delay)
    fetch = fetcher or _conditional_fetch

    if scope == "single":
        urls = [start_url]
    elif scope == "top":
        urls = discover_sitemap_urls(start_url, max_pages, gate, robots, fetcher)
        if not urls:
            urls = _discover_bfs(start_url, max_pages, gate, robots, fetcher)
    else:
        urls = discover_sitemap_urls(start_url, max_pages, gate, robots, fetcher)
        if not urls or scope == "max_pages":
            bfs = _discover_bfs(start_url, max_pages, gate, robots, fetcher)
            urls = list(dict.fromkeys(urls + bfs))[:max_pages]

    def _fetch_title(url: str) -> PageCandidate:
        try:
            fetch = fetcher or _conditional_fetch
            status, headers, body = fetch(url)
            if status == 200:
                ctype = headers.get("content-type", "").split(";")[0].strip().lower()
                if not ctype or ctype in _HTML_CONTENT_TYPES:
                    return PageCandidate(url=url, title=_parse_title(body.decode("utf-8", errors="ignore")))
        except Exception:  # noqa: BLE001
            pass
        return PageCandidate(url=url, title=None)

    if len(urls) <= 1:
        return [_fetch_title(u) for u in urls]

    import concurrent.futures

    max_workers = min(8, len(urls))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
        fetched = list(ex.map(_fetch_title, urls))
    by_url = {c.url: c for c in fetched}
    return [by_url[u] for u in urls if u in by_url]


def _word_count(markdown: str) -> int:
    return len(re.findall(r"\S+", markdown))


def _detect_lang(text: str) -> str | None:
    """Cheap heuristic: Arabic script present => ar, else en (flag only)."""
    if re.search(r"[\u0600-\u06FF]", text):
        return "ar"
    return "en"


def _crawl_one_url(
    url: str,
    known: dict[str, tuple[str | None, str | None]],
    gate: _DomainGate,
    robots: RobotsRules,
    fetcher: Callable | None,
    *,
    wait: bool = True,
) -> CrawlResult | None:
    if gate.blocked:
        return None
    if not robots.allowed(url):
        return None
    etag, last_modified = known.get(url, (None, None))
    try:
        fetch = fetcher or _conditional_fetch
        if wait:
            gate.wait_if_needed()
        try:
            status, headers, body = fetch(
                url, etag=etag, last_modified=last_modified
            )
        finally:
            if wait:
                gate.note_request()
        if status == 304:
            return CrawlResult(
                url=url, status="unchanged",
                etag=headers.get("etag") or etag,
                last_modified=headers.get("last-modified") or last_modified,
            )
        if status != 200:
            gate.note_failure()
            return CrawlResult(url=url, status="failed", error=f"HTTP {status}")
        ctype = headers.get("content-type", "").split(";")[0].strip().lower()
        if ctype and ctype not in _HTML_CONTENT_TYPES:
            return CrawlResult(url=url, status="failed", error=f"not HTML ({ctype})")
        markdown, title = _extract_markdown(body.decode("utf-8", errors="ignore"))
        if not markdown:
            return CrawlResult(url=url, status="failed", error="no extractable text")
        content_hash = sha256(markdown.encode("utf-8")).hexdigest()
        gate.note_success()
        return CrawlResult(
            url=url, status="crawled", title=title, markdown=markdown,
            word_count=_word_count(markdown), lang=_detect_lang(markdown),
            etag=headers.get("etag") or etag,
            last_modified=headers.get("last-modified") or last_modified,
            content_hash=content_hash,
        )
    except _DomainBlocked:
        return None
    except Exception as e:  # noqa: BLE001
        gate.note_failure()
        return CrawlResult(url=url, status="failed", error=str(e)[:300])


def _crawl_urls(
    urls: list[str],
    known: dict[str, tuple[str | None, str | None]],
    gate: _DomainGate,
    robots: RobotsRules,
    fetcher: Callable | None,
    *,
    parallel: bool = False,
) -> list[CrawlResult]:
    if not parallel or len(urls) <= 1:
        results: list[CrawlResult] = []
        for url in urls:
            r = _crawl_one_url(url, known, gate, robots, fetcher, wait=True)
            if r is None and gate.blocked:
                break
            if r is not None:
                results.append(r)
        return results

    # Fast path for explicit user selections: fetch in parallel with bounded
    # concurrency instead of serial 2s-per-page delays.
    import concurrent.futures

    results: list[CrawlResult] = []
    max_workers = min(6, max(1, len(urls)))
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {
            ex.submit(_crawl_one_url, url, known, gate, robots, fetcher, wait=False): url
            for url in urls
        }
        for fut in concurrent.futures.as_completed(futures):
            try:
                r = fut.result()
            except Exception as e:  # noqa: BLE001
                r = CrawlResult(url=futures[fut], status="failed", error=str(e)[:300])
            if r is not None:
                results.append(r)
    # Preserve a stable, deterministic order (same as input) for callers/tests.
    by_url = {r.url: r for r in results}
    return [by_url[u] for u in urls if u in by_url]


def crawl_site(
    start_url: str,
    scope: str = "subtree",
    max_pages: int = 200,
    known: dict[str, tuple[str | None, str | None]] | None = None,
    fetcher: Callable | None = None,
    urls: list[str] | None = None,
) -> list[CrawlResult]:
    """Crawl a site and return per-page results.

    ``known`` maps normalized URL -> (etag, last_modified) so unchanged pages
    come back as status "unchanged" without re-downloading. ``fetcher`` is
    injectable for tests and must accept ``(url, etag=, last_modified=)``
    and return ``(status, headers, body)``.
    """
    # Fail loudly on a blocked start URL (private/non-http) instead of
    # returning an empty crawl — the caller can mark the job failed.
    # Validate the raw URL first so UnsafeUrlError semantics carry through
    # for every invalid input (scheme, credentials, private host).
    assert_public_http_url(start_url)
    start_url = normalize_url(start_url)
    known = known or {}
    robots = RobotsRules(start_url, fetcher=fetcher)
    gate = _DomainGate(min_interval=robots.crawl_delay)

    explicit_selection = urls is not None
    if urls is not None:
        # Explicit selection (interactive flow): crawl EXACTLY these pages —
        # no discovery, no BFS. Same-origin + robots are still enforced.
        urls = _normalize_selected_urls(start_url, urls, max_pages)
    elif scope == "single":
        urls = [start_url]
    elif scope == "top":
        urls = discover_sitemap_urls(start_url, max_pages, gate, robots, fetcher)
        if not urls:
            urls = _discover_bfs(start_url, max(max_pages, 1), gate, robots, fetcher)
    else:
        urls = discover_sitemap_urls(start_url, max_pages, gate, robots, fetcher)
        if not urls or scope == "max_pages":
            bfs = _discover_bfs(start_url, max_pages, gate, robots, fetcher)
            merged = list(dict.fromkeys(urls + bfs))
            urls = merged[:max_pages]

    return _crawl_urls(urls, known, gate, robots, fetcher, parallel=explicit_selection)


def _robots_fetcher(fetcher: Callable | None) -> Callable[[str], str]:
    """Adapt the injectable page fetcher for robots.txt (returns text)."""
    if fetcher is not None:
        def via_fetcher(url: str) -> str:
            status, headers, body = fetcher(url, etag=None, last_modified=None)
            if status != 200:
                return ""
            return body.decode("utf-8", errors="ignore")
        return via_fetcher
    return _fetch_robots_text

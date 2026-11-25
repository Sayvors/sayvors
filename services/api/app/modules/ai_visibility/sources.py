"""SSRF-safe, bounded source snapshots for grounded research."""
from __future__ import annotations

import asyncio
import hashlib
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import trafilatura

from ...core.pinned_http import fetch_pinned_media
from ..auth.rate_limit import rate_limit
from .models import AiVisibilitySource
from .search import SearchResult

MAX_SOURCES_PER_RUN = 5
MAX_SOURCES_PER_DOMAIN = 2
MAX_SOURCE_BYTES = 2 * 1024 * 1024
SOURCE_TIMEOUT_SECONDS = 15.0
MAX_SOURCE_CHARS = 20_000
SOURCE_CONCURRENCY = 3
SOURCE_DOMAIN_RATE_LIMIT = 2
SOURCE_DOMAIN_RATE_WINDOW_SECONDS = 60
ALLOWED_CONTENT_TYPES = {"text/html", "application/xhtml+xml", "text/plain"}
TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "fbclid",
    "gclid",
}


def canonicalize_url(url: str) -> str:
    parts = urlsplit(url)
    query = urlencode(
        [
            (key, value)
            for key, value in parse_qsl(parts.query, keep_blank_values=True)
            if key.casefold() not in TRACKING_PARAMS
        ]
    )
    return urlunsplit(
        (
            parts.scheme.casefold(),
            parts.netloc.casefold(),
            parts.path or "/",
            query,
            "",
        )
    )


def select_sources(rows: list[SearchResult]) -> list[SearchResult]:
    seen_urls: set[str] = set()
    per_domain: dict[str, int] = {}
    selected: list[SearchResult] = []
    for row in rows:
        url = canonicalize_url(row.url)
        domain = urlsplit(url).hostname or ""
        if url in seen_urls or per_domain.get(domain, 0) >= MAX_SOURCES_PER_DOMAIN:
            continue
        seen_urls.add(url)
        per_domain[domain] = per_domain.get(domain, 0) + 1
        selected.append(SearchResult(url=url, title=row.title, snippet=row.snippet))
        if len(selected) == MAX_SOURCES_PER_RUN:
            break
    return selected


async def fetch_source(
    run_id: str, position: int, result: SearchResult
) -> AiVisibilitySource:
    url = canonicalize_url(result.url)
    row = AiVisibilitySource(
        run_id=run_id,
        position=position,
        url=url,
        canonical_url=url,
        title=result.title[:500],
        snippet=result.snippet[:2000],
    )
    try:
        domain = urlsplit(url).hostname or "unknown"
        if not await rate_limit(
            f"ai-vis:source:{domain}",
            SOURCE_DOMAIN_RATE_LIMIT,
            SOURCE_DOMAIN_RATE_WINDOW_SECONDS,
            fail_closed=True,
        ):
            raise ValueError("domain_rate_limited")
        body, content_type = await asyncio.to_thread(
            fetch_pinned_media,
            url,
            timeout=SOURCE_TIMEOUT_SECONDS,
            max_bytes=MAX_SOURCE_BYTES,
            user_agent="SayvorsResearchBot/1.0",
        )
        if content_type not in ALLOWED_CONTENT_TYPES:
            raise ValueError(f"unsupported_content_type:{content_type}")
        text = trafilatura.extract(
            body,
            output_format="txt",
            include_comments=False,
            include_tables=False,
            favor_precision=True,
        )
        if not text:
            raise ValueError("empty_extracted_text")
        excerpt = text.strip()[:MAX_SOURCE_CHARS]
        row.excerpt = excerpt
        row.content_hash = hashlib.sha256(excerpt.encode("utf-8")).hexdigest()
        row.http_status = 200
    except Exception as exc:
        row.fetch_error = str(exc)[:1000]
    return row


async def fetch_sources(
    db, run_id: str, rows: list[SearchResult]
) -> list[AiVisibilitySource]:
    semaphore = asyncio.Semaphore(SOURCE_CONCURRENCY)

    async def _one(position: int, result: SearchResult):
        async with semaphore:
            return await fetch_source(run_id, position, result)

    snapshots = await asyncio.gather(
        *[
            _one(position, result)
            for position, result in enumerate(select_sources(rows))
        ]
    )
    db.add_all(snapshots)
    await db.commit()
    return snapshots

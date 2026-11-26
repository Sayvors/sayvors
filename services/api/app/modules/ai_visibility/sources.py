"""SSRF-safe, bounded source snapshots for grounded research."""
from __future__ import annotations

import asyncio
import hashlib
import re
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
# Absolute outbound anchors inside a fetched page; counted for the run's
# factual coverage metrics ("this many links existed in what we read").
_LINK_ANCHOR_RE = re.compile(rb"""<a\b[^>]*?href=["']?https?://""", re.I)
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


def select_sources(
    rows: list[SearchResult], *, max_sources: int = MAX_SOURCES_PER_RUN
) -> list[SearchResult]:
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
        if len(selected) == max_sources:
            break
    return selected


async def fetch_source(
    run_id: str, position: int, result: SearchResult
) -> tuple[AiVisibilitySource, dict]:
    """Fetch one page and return its snapshot plus raw-coverage stats.

    The stats describe what the page actually contributed (text words,
    outbound links) so the research UI can report facts instead of vibes.
    """
    url = canonicalize_url(result.url)
    row = AiVisibilitySource(
        run_id=run_id,
        position=position,
        url=url,
        canonical_url=url,
        title=result.title[:500],
        snippet=result.snippet[:2000],
    )
    stats = {"read": False, "links_found": 0, "words": 0}
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
        description = ""
        try:
            metadata = trafilatura.extract_metadata(body)
            if metadata:
                if metadata.title:
                    row.title = metadata.title.strip()[:500]
                description = (metadata.description or "").strip()[:2000]
                if description:
                    row.snippet = description
        except Exception:
            # Metadata is an enrichment, not a reason to discard readable text.
            description = ""
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
        if description and description not in excerpt:
            excerpt = f"{description}\n\n{excerpt}"[:MAX_SOURCE_CHARS]
        row.excerpt = excerpt
        row.content_hash = hashlib.sha256(excerpt.encode("utf-8")).hexdigest()
        row.http_status = 200
        stats["read"] = True
        stats["links_found"] = len(_LINK_ANCHOR_RE.findall(body))
        stats["words"] = len(excerpt.split())
    except Exception as exc:
        row.fetch_error = str(exc)[:1000]
    return row, stats


async def fetch_sources(
    db, run_id: str, rows: list[SearchResult], *, max_sources: int = MAX_SOURCES_PER_RUN
) -> tuple[list[AiVisibilitySource], dict]:
    semaphore = asyncio.Semaphore(SOURCE_CONCURRENCY)

    async def _one(position: int, result: SearchResult):
        async with semaphore:
            return await fetch_source(run_id, position, result)

    fetched = await asyncio.gather(
        *[
            _one(position, result)
            for position, result in enumerate(
                select_sources(rows, max_sources=max_sources)
            )
        ]
    )
    snapshots = [row for row, _stats in fetched]
    stats = {
        "pages_read": sum(1 for _row, s in fetched if s["read"]),
        "pages_failed": sum(1 for _row, s in fetched if not s["read"]),
        "links_found": sum(s["links_found"] for _row, s in fetched),
        "words_read": sum(s["words"] for _row, s in fetched),
    }
    db.add_all(snapshots)
    await db.commit()
    return snapshots, stats

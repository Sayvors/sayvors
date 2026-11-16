"""Databank activity feed (§31 Phase B UI support).

Composes an organized log from existing append-only state — no new write
paths, so the feed can never drift from what actually happened:

- ingest jobs (per document: queued → parsing → … → done/failed, timestamps)
- crawl source runs (latest pass per website source, per-page counts)
- failed crawl pages (recent errors, so failures are diagnosable in-product
  instead of only in worker logs)
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .crawl_service import page_status_counts_for_sources
from .models import CrawlPage, CrawlSource, Document, IngestJob

# Feed length caps keep the payload bounded no matter how busy a bank is.
_MAX_EVENTS = 50
_MAX_ERROR_EVENTS = 10

# Map ingest-job status to a stable feed status the UI can color.
_INGEST_FEED_STATUS = {
    "queued": "queued",
    "parsing": "running",
    "chunking": "running",
    "embedding": "running",
    "indexing": "running",
    "completed": "done",
    "failed": "failed",
}


async def databank_activity(
    db: AsyncSession, *, databank_id: str, user_id: str
) -> list[dict]:
    """Latest activity events for one databank, newest first."""
    events: list[dict] = []

    # ── Ingest jobs (document processing pipeline) ──────────────
    rows = (
        await db.execute(
            select(IngestJob, Document.filename)
            .outerjoin(Document, IngestJob.document_id == Document.id)
            .where(
                IngestJob.databank_id == databank_id,
                IngestJob.user_id == user_id,
            )
            .order_by(IngestJob.created_at.desc())
            .limit(30)
        )
    ).all()
    for job, doc_filename in rows:
        status = _INGEST_FEED_STATUS.get(job.status, job.status)
        display = doc_filename or job.document_id or "databank"
        detail = job.stage or ""
        if job.error:
            detail = job.error[:200]
        events.append({
            "type": "ingest",
            "status": status,
            "title": display,
            "detail": detail,
            "progress": job.progress or 0,
            "at": (job.updated_at or job.created_at),
        })

    # ── Crawl source runs ───────────────────────────────────────
    sources = (
        await db.execute(
            select(CrawlSource)
            .where(
                CrawlSource.databank_id == databank_id,
                CrawlSource.user_id == user_id,
            )
        )
    ).scalars().all()
    if sources:
        status_counts = await page_status_counts_for_sources(db, [s.id for s in sources])
        for source in sources:
            counts = status_counts.get(source.id, {})
            crawled = counts.get("crawled", 0) + counts.get("unchanged", 0)
            failed = counts.get("failed", 0)
            at = source.last_sync_at or source.updated_at
            events.append({
                "type": "crawl",
                "status": source.last_status,
                "title": source.start_url,
                "detail": (
                    f"{crawled} pages crawled, {failed} failed"
                    if source.last_status != "failed"
                    else (source.error or "crawl failed")[:200]
                ),
                "progress": None,
                "at": at,
            })

            # ── Failed pages for this source (bounded) ──────────────
            failed_pages = (
                await db.execute(
                    select(CrawlPage)
                    .where(
                        CrawlPage.source_id == source.id,
                        CrawlPage.status == CrawlPage.STATUS_FAILED,
                    )
                    .order_by(CrawlPage.updated_at.desc())
                    .limit(_MAX_ERROR_EVENTS)
                )
            ).scalars().all()
            for page in failed_pages:
                events.append({
                    "type": "error",
                    "status": "failed",
                    "title": page.url,
                    "detail": (page.error or "fetch failed")[:200],
                    "progress": None,
                    "at": page.updated_at or page.fetched_at,
                })

    def _sort_key(event: dict) -> datetime:
        at = event.get("at")
        if isinstance(at, datetime):
            # SQLite returns naive datetimes; treat them as UTC so ordering
            # is stable across dev (SQLite) and prod (Postgres).
            if at.tzinfo is None:
                at = at.replace(tzinfo=timezone.utc)
            return at
        return datetime.min.replace(tzinfo=timezone.utc)

    events.sort(key=_sort_key, reverse=True)
    return events[:_MAX_EVENTS]

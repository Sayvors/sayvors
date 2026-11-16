"""Crawl source CRUD (§31 Phase 1 API support).

Thin service over the CrawlSource/CrawlPage models with tenant ownership checks
mirroring the databank service. The sync worker (Phase 2) consumes these rows;
the endpoints here manage them and never touch the network.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .crawler import normalize_url, same_origin
from .models import CrawlPage, CrawlSource

DEFAULT_NEXT_SYNC_DELAY_MINUTES = 5
MAX_SELECTED_URLS = 500


async def get_crawl_source(db: AsyncSession, databank_id: str,
                           user_id: str, source_id: str) -> CrawlSource:
    source = (
        await db.execute(
            select(CrawlSource).where(
                CrawlSource.id == source_id,
                CrawlSource.databank_id == databank_id,
                CrawlSource.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if source is None:
        raise LookupError("Crawl source not found")
    return source


async def create_crawl_source(
    db: AsyncSession,
    *,
    databank_id: str,
    user_id: str,
    start_url: str,
    scope: str,
    max_pages: int,
    sync_enabled: bool,
    sync_interval_minutes: int,
    urls: list[str] | None = None,
) -> CrawlSource:
    source = CrawlSource(
        id=str(uuid.uuid4()),
        databank_id=databank_id,
        user_id=user_id,
        start_url=start_url,
        scope=scope,
        max_pages=max_pages,
        sync_enabled=sync_enabled,
        sync_interval_minutes=sync_interval_minutes,
    )
    # Interactive selection: persist exactly the user-ticked pages as
    # CrawlPage rows (status "discovered"). The worker crawls only these.
    selected = _normalize_selected(start_url, urls or [])
    if sync_enabled:
        source.next_sync_at = datetime.now(timezone.utc) + timedelta(
            minutes=DEFAULT_NEXT_SYNC_DELAY_MINUTES
        )
    elif selected:
        # One-shot crawl: run immediately. The worker sets next_sync_at=None
        # after a successful run when sync is disabled (no recurring schedule).
        source.next_sync_at = datetime.now(timezone.utc)
    db.add(source)
    await db.flush()

    for url in selected:
        db.add(CrawlPage(
            id=str(uuid.uuid4()),
            source_id=source.id,
            url=url,
        ))
    await db.commit()
    await db.refresh(source)
    return source


def _normalize_selected(start_url: str, urls: list[str]) -> list[str]:
    """Normalize + dedup selected URLs, bounded to MAX_SELECTED_URLS.

    Only same-origin URLs (relative to the source's start URL) are kept: the
    selection UI only ever offers our own discovery results, but a crafted
    client must not be able to make the worker crawl arbitrary third-party
    sites by passing them as "selected" pages.
    """
    seen: set[str] = set()
    out: list[str] = []
    for raw in urls:
        if len(out) >= MAX_SELECTED_URLS:
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


async def list_crawl_sources(
    db: AsyncSession, *, databank_id: str, user_id: str,
    limit: int, offset: int,
) -> tuple[list[CrawlSource], int]:
    base = select(CrawlSource).where(
        CrawlSource.databank_id == databank_id,
        CrawlSource.user_id == user_id,
    )
    total = (await db.execute(
        select(func.count()).select_from(base.subquery())
    )).scalar() or 0
    sources = (
        await db.execute(
            base.order_by(CrawlSource.created_at.desc()).limit(limit).offset(offset)
        )
    ).scalars().all()
    return list(sources), int(total)


async def page_count_for_sources(db: AsyncSession, source_ids: list[str]) -> dict[str, int]:
    if not source_ids:
        return {}
    rows = (
        await db.execute(
            select(CrawlPage.source_id, func.count())
            .where(CrawlPage.source_id.in_(source_ids))
            .group_by(CrawlPage.source_id)
        )
    ).all()
    return {source_id: int(count) for source_id, count in rows}


async def page_status_counts_for_sources(db: AsyncSession, source_ids: list[str]) -> dict[str, dict[str, int]]:
    """Per-source counts grouped by crawl-page status (for progress UI)."""
    if not source_ids:
        return {}
    rows = (
        await db.execute(
            select(CrawlPage.source_id, CrawlPage.status, func.count())
            .where(CrawlPage.source_id.in_(source_ids))
            .group_by(CrawlPage.source_id, CrawlPage.status)
        )
    ).all()
    out: dict[str, dict[str, int]] = {}
    for source_id, status, count in rows:
        out.setdefault(source_id, {})[status] = int(count)
    return out


async def update_crawl_source(
    db: AsyncSession,
    *,
    databank_id: str,
    user_id: str,
    source_id: str,
    values: dict,
) -> CrawlSource:
    source = await get_crawl_source(db, databank_id, user_id, source_id)
    enabled = values.get("sync_enabled", source.sync_enabled)
    interval = values.get("sync_interval_minutes", source.sync_interval_minutes)
    if enabled and not source.sync_enabled and source.next_sync_at is None:
        values["next_sync_at"] = datetime.now(timezone.utc) + timedelta(
            minutes=DEFAULT_NEXT_SYNC_DELAY_MINUTES
        )
    if not enabled:
        values["next_sync_at"] = None
    for key, value in values.items():
        setattr(source, key, value)
    await db.commit()
    await db.refresh(source)
    return source


async def delete_crawl_source(
    db: AsyncSession, *, databank_id: str, user_id: str, source_id: str,
) -> bool:
    source = await get_crawl_source(db, databank_id, user_id, source_id)
    # Delete pages explicitly: Postgres cascades via the FK, but SQLite (the
    # test schema) does not enforce FK cascades — explicit deletes keep both
    # databases identical.
    await db.execute(
        delete(CrawlPage).where(CrawlPage.source_id == source.id)
    )
    await db.delete(source)
    await db.commit()
    return True

"""Crawler data model (§31 Phase 0): crawl_sources + crawl_pages.

Pins the schema contract the Phase 1 crawler and Phase 2 sync worker build on:
defaults, constants, and the (source_id, url) upsert guard that fixes the
duplicate-document bug.
"""
import uuid

import pytest
from sqlalchemy.exc import IntegrityError

from app.modules.rag.models import CrawlPage, CrawlSource, Databank

_BANK = "crawl-test-bank-0001"
_USER = "crawl-test-user-0001"


async def _seed_db(db) -> str:
    db.add(Databank(id=_BANK, user_id=_USER, name="Crawl Test Bank"))
    await db.commit()
    return _BANK


async def _add_source(db, bank_id: str, **overrides) -> CrawlSource:
    source = CrawlSource(
        id=str(uuid.uuid4()),
        user_id=_USER,
        databank_id=bank_id,
        **{"start_url": "https://example.com", **overrides},
    )
    db.add(source)
    await db.commit()
    return source


@pytest.mark.asyncio
async def test_crawl_source_defaults(db):
    bank_id = await _seed_db(db)
    source = await _add_source(db, bank_id)

    assert source.scope == CrawlSource.SCOPE_SUBTREE
    assert source.max_pages == CrawlSource.DEFAULT_MAX_PAGES
    assert source.sync_enabled is False
    assert source.sync_interval_minutes == CrawlSource.DEFAULT_SYNC_INTERVAL_MINUTES
    assert source.last_status == CrawlSource.STATUS_IDLE
    assert source.next_sync_at is None
    assert source.last_sync_at is None


@pytest.mark.asyncio
async def test_crawl_source_custom_values(db):
    bank_id = await _seed_db(db)
    source = await _add_source(
        db,
        bank_id,
        scope=CrawlSource.SCOPE_TOP,
        max_pages=25,
        sync_enabled=True,
        sync_interval_minutes=120,
    )
    assert source.scope == CrawlSource.SCOPE_TOP
    assert source.max_pages == 25
    assert source.sync_enabled is True
    assert source.sync_interval_minutes == 120


@pytest.mark.asyncio
async def test_crawl_page_defaults_and_link(db):
    bank_id = await _seed_db(db)
    source = await _add_source(db, bank_id)

    page = CrawlPage(
        id=str(uuid.uuid4()),
        source_id=source.id,
        url="https://example.com/",
    )
    db.add(page)
    await db.commit()

    assert page.status == CrawlPage.STATUS_DISCOVERED
    assert page.word_count == 0
    assert page.content_hash is None
    assert page.document_id is None


@pytest.mark.asyncio
async def test_crawl_page_content_hash_and_document_link(db):
    bank_id = await _seed_db(db)
    source = await _add_source(db, bank_id)

    page = CrawlPage(
        id=str(uuid.uuid4()),
        source_id=source.id,
        url="https://example.com/services",
        title="Services",
        status=CrawlPage.STATUS_CRAWLED,
        content_hash="a" * 64,
        word_count=120,
        lang="en",
        document_id="doc-crawl-0001",
    )
    db.add(page)
    await db.commit()
    await db.refresh(page)

    assert page.status == CrawlPage.STATUS_CRAWLED
    assert page.content_hash == "a" * 64
    assert page.word_count == 120
    assert page.lang == "en"
    assert page.document_id == "doc-crawl-0001"


@pytest.mark.asyncio
async def test_crawl_page_unique_url_per_source(db):
    """The upsert guard: the same URL cannot be registered twice for a source."""
    bank_id = await _seed_db(db)
    source = await _add_source(db, bank_id)

    db.add(CrawlPage(id=str(uuid.uuid4()), source_id=source.id, url="https://example.com/"))
    await db.commit()

    db.add(CrawlPage(id=str(uuid.uuid4()), source_id=source.id, url="https://example.com/"))
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()


@pytest.mark.asyncio
async def test_crawl_same_url_allowed_across_sources(db):
    bank_id = await _seed_db(db)
    source_a = await _add_source(db, bank_id)
    source_b = await _add_source(db, bank_id, start_url="https://other.example.com")

    db.add(CrawlPage(id=str(uuid.uuid4()), source_id=source_a.id, url="https://example.com/"))
    db.add(CrawlPage(id=str(uuid.uuid4()), source_id=source_b.id, url="https://example.com/"))
    await db.commit()  # must not raise


@pytest.mark.asyncio
async def test_crawl_source_enum_constants_are_stable(db):
    # The migration/schema and the UI share these exact strings.
    assert CrawlSource.SCOPES == ("top", "subtree", "max_pages")
    assert CrawlPage.STATUSES == ("discovered", "crawled", "unchanged", "failed", "excluded")
    assert CrawlSource.MIN_SYNC_INTERVAL_MINUTES == 60
    assert CrawlSource.MAX_PAGES_LIMIT == 500

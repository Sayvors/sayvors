"""Crawl source worker (§31 Phase 2): a due source crawls ONLY its selected
pages, upserts documents, and records per-page state — end to end against a
FakeSite, no network.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.modules.rag.jobs import _process_due_crawl_sources
from app.modules.rag.models import CrawlPage, CrawlSource, Databank, Document

# Dedicated in-memory engine for the worker tests: the worker opens its own
# sessions, so it gets its own engine (not conftest's static-pool engine) to
# guarantee seed + worker + verification all see the same database.
WORKER_ENGINE = create_async_engine(
    "sqlite+aiosqlite:///:memory:",
    poolclass=StaticPool,
    connect_args={"check_same_thread": False},
)
WORKER_SESSION = async_sessionmaker(WORKER_ENGINE, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture(autouse=True)
async def _isolate_worker_storage(monkeypatch):
    """The worker opens app.database.async_session and writes via storage:
    point both at a dedicated test DB / a no-op store so nothing touches the
    real Postgres or S3."""
    async with WORKER_ENGINE.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr("app.modules.rag.jobs.async_session", WORKER_SESSION)
    monkeypatch.setattr("app.core.storage.put_doc", lambda *a, **k: None)

_BANK = "crawl-worker-bank-0001"
_USER = "crawl-worker-user-0001"


class FakeSite:
    def __init__(self):
        self.pages: dict[str, dict] = {}
        self.robots = ""

    def add_page(self, path, html, etag='W/"v1"'):
        self.pages[path] = {"html": html, "etag": etag}

    def __call__(self, url, *, etag=None, last_modified=None):
        parsed = __import__("urllib.parse", fromlist=["urlparse"]).urlparse(url)
        if parsed.path == "/robots.txt":
            return (200, {"content-type": "text/plain"}, self.robots.encode())
        page = self.pages.get(parsed.path)
        if page is None:
            return (404, {"content-type": "text/html"}, b"")
        if etag and etag == page["etag"]:
            return (304, {"etag": page["etag"]}, b"")
        return (200, {"content-type": "text/html", "etag": page["etag"]}, page["html"].encode())


async def _seed_due_source(*, selected=None, interval_minutes=60, enabled=False):
    bank_id = str(uuid.uuid4())
    async with WORKER_SESSION() as db:
        db.add(Databank(id=bank_id, user_id=_USER, name="Worker Bank"))
        source = CrawlSource(
            id=str(uuid.uuid4()),
            databank_id=bank_id,
            user_id=_USER,
            start_url="https://example.com/",
            scope="subtree",
            max_pages=50,
            sync_enabled=enabled,
            sync_interval_minutes=interval_minutes,
            next_sync_at=datetime.now(timezone.utc) - timedelta(minutes=1),
        )
        db.add(source)
        await db.flush()
        for path in selected or ["/"]:
            db.add(CrawlPage(id=str(uuid.uuid4()), source_id=source.id, url=f"https://example.com{path}"))
        await db.commit()
        return source.id, bank_id


@pytest.mark.asyncio
async def test_worker_crawls_only_selected_pages(monkeypatch):
    site = FakeSite()
    site.add_page("/", "<html><head><title>Home</title></head><body><p>Welcome</p></body></html>")
    site.add_page("/about", "<html><head><title>About</title></head><body><p>Our story</p></body></html>")
    site.add_page("/private", "<html><head><title>Private</title></head><body><p>Secret</p></body></html>")

    monkeypatch.setattr("app.modules.rag.crawler._conditional_fetch", site)
    monkeypatch.setattr("app.modules.rag.crawler._fetch_robots_text", lambda url: site(url, etag=None, last_modified=None)[2].decode("utf-8", errors="ignore"))
    monkeypatch.setattr("app.core.http.resolve_public_ips", lambda host: ["93.184.216.34"])

    source_id, bank_id = await _seed_due_source(selected=["/", "/about"])

    await _process_due_crawl_sources()

    async with WORKER_SESSION() as db:
        docs = (await db.execute(
            select(Document).where(Document.databank_id == bank_id)
        )).scalars().all()
        # Exactly the two selected pages became documents — /private was never crawled.
        assert sorted(d.source_url for d in docs) == [
            "https://example.com/",
            "https://example.com/about",
        ]
        assert all(d.file_type == "md" for d in docs)
        # Phase A: language-neutral grouping on documents (no /en prefix here,
        # so each page is its own variant group with no URL language).
        assert all(d.variant_group in ("/", "/about") for d in docs)
        assert all(d.lang in (None, "en") for d in docs)

        pages = (await db.execute(select(CrawlPage).where(CrawlPage.source_id == source_id))).scalars().all()
        assert all(p.status == "crawled" for p in pages)
        assert all(p.content_hash for p in pages)
        assert all(p.title for p in pages)

        source = (await db.execute(select(CrawlSource).where(CrawlSource.id == source_id))).scalar_one()
        assert source.last_status == "success"
        assert source.last_sync_at is not None
        assert source.next_sync_at is None  # one-shot (sync disabled)


@pytest.mark.asyncio
async def test_worker_reuses_etag_for_unchanged_pages(monkeypatch):
    site = FakeSite()
    site.add_page("/", "<html><head><title>Home</title></head><body><p>Welcome</p></body></html>")
    site.requests = []

    monkeypatch.setattr("app.modules.rag.crawler._conditional_fetch", site)
    monkeypatch.setattr("app.modules.rag.crawler._fetch_robots_text", lambda url: site(url, etag=None, last_modified=None)[2].decode("utf-8", errors="ignore"))
    monkeypatch.setattr("app.core.http.resolve_public_ips", lambda host: ["93.184.216.34"])

    source_id, bank_id = await _seed_due_source(selected=["/"], enabled=True, interval_minutes=60)

    from app.modules.rag.jobs import _process_due_crawl_sources as _worker_run

    await _worker_run()

    # Re-arm the next check (sync enabled => next_sync_at is interval ahead).
    from sqlalchemy import update

    async with WORKER_SESSION() as db:
        await db.execute(
            update(CrawlSource)
            .where(CrawlSource.id == source_id)
            .values(next_sync_at=datetime.now(timezone.utc) - timedelta(minutes=1))
        )
        await db.commit()

    await _worker_run()  # second run: same ETag -> unchanged
    async with WORKER_SESSION() as db:
        src = (await db.execute(select(CrawlSource).where(CrawlSource.id == source_id))).scalar_one()
        assert src.last_status == "success"
        assert src.next_sync_at is not None  # sync enabled -> next interval scheduled
        pages = (await db.execute(select(CrawlPage).where(CrawlPage.source_id == source_id))).scalars().all()
        assert pages[0].status == "unchanged"
        docs = (await db.execute(
            select(Document).where(Document.databank_id == bank_id)
        )).scalars().all()
        assert len(docs) == 1  # no duplicate document on re-crawl

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

from ...database import async_session
from .cache import set_progress
from .chunker import chunk_text
from .crawler import crawl_site, path_lang, variant_group
from .document_structure import build_structured_doc
from .embeddings import get_embedding_provider
from .models import CrawlPage, CrawlSource, Document, DocumentChunk, IngestJob, ScrapeJob
from .summarizer import maybe_enrich_document

logger = logging.getLogger(__name__)

SEMAPHORE = asyncio.Semaphore(4)
_worker_task: asyncio.Task | None = None
_running = False
# Fire-and-forget business-profile refreshes — kept referenced so the event
# loop never garbage-collects a task mid-flight (asyncio requirement).
_profile_tasks: set[asyncio.Task] = set()


async def enqueue_job(job_id: str) -> None:
    try:
        from ...modules.redis.client import get_redis

        redis = await get_redis()
        from .cache import QUEUE_KEY

        await redis.rpush(QUEUE_KEY, job_id)
    except Exception:
        logger.warning("Redis unavailable, job %s will be picked up by DB polling", job_id)


async def start_worker() -> None:
    global _worker_task, _running
    if _running:
        return
    await _recover_stale_jobs()
    _running = True
    _worker_task = asyncio.create_task(_worker_loop())


async def stop_worker() -> None:
    global _running, _worker_task
    _running = False
    if _worker_task:
        _worker_task.cancel()
        _worker_task = None


async def _recover_stale_jobs() -> None:
    try:
        async with async_session() as db:
            stale_cutoff = datetime.now(timezone.utc) - timedelta(minutes=10)
            await db.execute(
                update(IngestJob)
                .where(
                    IngestJob.status.in_(["parsing", "chunking", "embedding", "indexing"]),
                    IngestJob.updated_at < stale_cutoff,
                )
                .values(status="queued", stage="Re-queued after crash", progress=0)
            )
            await db.commit()
    except Exception:
        logger.exception("Failed to recover stale jobs")


async def _worker_loop() -> None:
    while _running:
        job_id = await _dequeue_job()
        if job_id:
            await _process_job(job_id)
        else:
            await _process_pending_scrape()
            # Process all currently-due sources so a newly created one-shot
            # crawl starts immediately instead of waiting for poll cycles.
            processed_any = False
            for _ in range(10):
                did = await _process_due_crawl_sources()
                if not did:
                    break
                processed_any = True
            await asyncio.sleep(0.1 if processed_any else 0.5)


async def _dequeue_job() -> str | None:
    # Try Redis first — this is just a wake-up hint
    try:
        from ...modules.redis.client import get_redis

        redis = await get_redis()
        from .cache import QUEUE_KEY

        _, job_id = await redis.blpop(QUEUE_KEY, timeout=2)
        return job_id
    except Exception:
        pass

    # DB fallback: atomic claim with UPDATE … RETURNING
    try:
        async with async_session() as db:
            result = await db.execute(
                update(IngestJob)
                .where(IngestJob.status == "queued")
                .values(status="parsing", stage="Claimed", updated_at=datetime.now(timezone.utc))
                .returning(IngestJob.id)
                .execution_options(synchronize_session=False)
            )
            row = result.first()
            if row:
                await db.commit()
                return str(row[0])
    except Exception:
        logger.exception("DB dequeue failed")
    return None


async def _process_job(job_id: str) -> None:
    async with SEMAPHORE:
        async with async_session() as db:
            # DB claim is the single source of truth
            result = await db.execute(
                select(IngestJob).where(IngestJob.id == job_id)
            )
            job = result.scalar_one_or_none()
            if not job:
                return

            # If not yet claimed, atomically claim it (single worker case)
            if job.status != "parsing":
                claim_result = await db.execute(
                    update(IngestJob)
                    .where(IngestJob.id == job_id, IngestJob.status == "queued")
                    .values(status="parsing", stage="Starting", updated_at=datetime.now(timezone.utc))
                )
                if claim_result.rowcount == 0:
                    # Another worker claimed it — skip
                    return
                await db.commit()
                job.status = "parsing"

            await set_progress(job_id, 0, job.stage or "Starting...")

            try:
                if job.document_id:
                    await _process_document_job(job, db)
                else:
                    await _process_databank_job(job, db)

                job.status = "completed"
                job.progress = 100
                job.stage = "Done"
                await db.commit()
                await set_progress(job_id, 100, "Done")
                # A crawl produces one ingest job per page (58 on a typical
                # site). Refreshing the tenant business card after EACH of them
                # wasted 58 LLM calls and buried the log in warnings. Only a
                # real file upload should re-distill the business card.
                if job.job_type == "upload":
                    _maybe_refresh_business_profile(job.user_id)
                # Phase C: LLM-polish the page summary of scraped docs
                # (fire-and-forget, budget-gated, off by default).
                if job.job_type == "scrape" and job.document_id:
                    maybe_enrich_document(str(job.document_id))
            except Exception as e:
                logger.exception("Job %s failed", job_id)
                job.status = "failed"
                job.error = str(e)[:2000]
                job.stage = "Failed"
                await db.commit()
                await set_progress(job_id, job.progress, "Failed")


def _maybe_refresh_business_profile(user_id: str | None) -> None:
    """After a successful ingest, ask the LLM to (re)distill the tenant's
    business card from the fresh content. Fire-and-forget with its own DB
    session so the ingest job never waits on an LLM call, and a failure
    here can never mark a job failed. The service itself skips edited
    cards and debounces multi-file uploads."""
    if not user_id:
        return

    async def _run() -> None:
        try:
            from ...modules.profile.business_profile import generate_business_profile

            async with async_session() as session:
                await generate_business_profile(user_id, session, force=False)
            logger.info("Business profile refreshed for %s", user_id)
        except ValueError as e:
            # No model enabled / nothing to generate from — expected states.
            logger.info("Business profile refresh skipped for %s: %s", user_id, e)
        except Exception:
            logger.exception("Business profile refresh failed for %s", user_id)

    task = asyncio.create_task(_run())
    _profile_tasks.add(task)
    task.add_done_callback(_profile_tasks.discard)


async def _process_document_job(job: IngestJob, db) -> None:
    from .service import _parse_document, _embed_and_store

    result = await db.execute(
        select(Document).where(Document.id == job.document_id)
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise ValueError(f"Document {job.document_id} not found")

    job.stage = "Parsing..."
    job.progress = 10
    await db.commit()
    await set_progress(str(job.id), 10, "Parsing...")

    text_content = await _parse_document(doc)

    job.stage = "Chunking..."
    job.progress = 30
    await db.commit()
    await set_progress(str(job.id), 30, "Chunking...")

    # Chunk provenance (§31 Phase B): every chunk knows its document's
    # language and source so search can filter/prefer per language.
    chunks = chunk_text(text_content, metadata={
        "lang": doc.lang,
        "source_url": doc.source_url,
        "doc_title": (doc.meta or {}).get("title") or doc.filename,
    })

    doc.status = "processing"
    doc.chunk_count = len(chunks)
    await db.commit()

    # Reprocessing must replace chunks, not duplicate them.
    await db.execute(
        DocumentChunk.__table__.delete().where(DocumentChunk.document_id == doc.id)
    )
    await db.commit()

    await _embed_and_store(doc, chunks, job)


async def _process_databank_job(job: IngestJob, db) -> None:
    result = await db.execute(
        select(Document).where(
            Document.databank_id == job.databank_id,
            Document.status == "pending",
        )
    )
    docs = list(result.scalars().all())

    if not docs:
        return

    total = len(docs)
    for i, doc in enumerate(docs):
        await _process_document_job_single(doc, job, db, i, total)


async def _process_document_job_single(doc, job, db, index, total) -> None:
    from .service import _parse_document, _embed_and_store

    base_progress = 10 + int(80 * index / total)
    doc_progress = int(80 / total)

    job.stage = f"Parsing {doc.filename}..."
    job.progress = base_progress
    await db.commit()
    await set_progress(str(job.id), base_progress, job.stage)

    text_content = await _parse_document(doc)

    chunk_progress = base_progress + doc_progress // 3
    job.stage = f"Chunking {doc.filename}..."
    job.progress = chunk_progress
    await db.commit()
    await set_progress(str(job.id), chunk_progress, job.stage)

    chunks = chunk_text(text_content, metadata={
        "lang": doc.lang,
        "source_url": doc.source_url,
        "doc_title": (doc.meta or {}).get("title") or doc.filename,
    })

    doc.status = "processing"
    doc.chunk_count = len(chunks)
    await db.commit()

    # Reprocessing must replace chunks, not duplicate them.
    await db.execute(
        DocumentChunk.__table__.delete().where(DocumentChunk.document_id == doc.id)
    )
    await db.commit()

    embed_progress = base_progress + (doc_progress * 2) // 3
    job.stage = f"Embedding {doc.filename}..."
    job.progress = embed_progress
    await db.commit()
    await set_progress(str(job.id), embed_progress, job.stage)

    await _embed_and_store(doc, chunks, job)


async def _process_due_crawl_sources() -> bool:
    """Claim one due crawl source and crawl only its selected pages.

    §31 Phase 2 core. The source rows are the sync state machine: the worker
    claims one due source (``next_sync_at <= now``) under a row lock, crawls
    exactly the pages the tenant selected (``crawl_pages`` rows), upserts the
    extracted markdown as Documents, and records per-page statuses +
    conditional-GET validators for the next check.

    One-shot sources (``sync_enabled`` false) get ``next_sync_at = None``
    after the run; scheduled sources get the next interval. The adaptive
    interval ladder (unchanged 1h -> 6h -> 24h) is a follow-up refinement.
    """
    import uuid

    from .crawler import crawl_site

    async with async_session() as db:
        now = datetime.now(timezone.utc)
        # Fetch candidate sources ordered by due time, then pick the oldest due
        # in Python: SQLite stores timestamptz as strings where a SQL-side
        # `<= now` comparison is unreliable, and the volume (1000s of sites,
        # one worker) makes the in-process filter trivially cheap.
        rows = (
            await db.execute(
                select(CrawlSource)
                .where(
                    CrawlSource.next_sync_at.is_not(None),
                    CrawlSource.last_status != CrawlSource.STATUS_RUNNING,
                )
                .order_by(CrawlSource.next_sync_at)
                .limit(20)
            )
        ).scalars().all()
        source = None
        for s in rows:
            next_at = s.next_sync_at
            if next_at is None:
                continue
            ref = now
            # SQLite hands back naive datetimes (no tz storage); Postgres is
            # tz-aware. Compare on a matching basis.
            if next_at.tzinfo is None:
                ref = now.replace(tzinfo=None)
            if next_at <= ref:
                source = s
                break
        if source is None:
            return False
        # Claim under the row: a concurrent worker that already flipped it to
        # "running" makes this UPDATE match 0 rows and we back off. Any
        # non-running state (idle/success/failed) is claimable — this is what
        # lets a scheduled source be re-crawled after a successful run.
        claimed = await db.execute(
            update(CrawlSource)
            .where(
                CrawlSource.id == source.id,
                CrawlSource.last_status != CrawlSource.STATUS_RUNNING,
            )
            .values(
                last_status=CrawlSource.STATUS_RUNNING,
                error=None,
                updated_at=now,
            )
        )
        if claimed.rowcount == 0:
            await db.rollback()
            return False
        await db.commit()
        source_id, databank_id, user_id = source.id, source.databank_id, source.user_id
        scope, max_pages = source.scope, source.max_pages

        pages_result = await db.execute(
            select(CrawlPage).where(CrawlPage.source_id == source_id)
        )
        pages = list(pages_result.scalars().all())

    known = {
        p.url: (p.http_etag, p.http_last_modified)
        for p in pages
        if p.status != CrawlPage.STATUS_FAILED
    }
    selected_urls = [p.url for p in pages]
    try:
        results = await asyncio.get_event_loop().run_in_executor(
            None, crawl_site, source.start_url, scope, max_pages, known, None, selected_urls
        )
    except Exception as e:
        logger.exception("Crawl source %s failed", source_id)
        async with async_session() as db:
            done = (
                await db.execute(select(CrawlSource).where(CrawlSource.id == source_id))
            ).scalar_one_or_none()
            if done:
                done.last_status = CrawlSource.STATUS_FAILED
                done.error = str(e)[:2000]
                done.last_sync_at = datetime.now(timezone.utc)
                done.next_sync_at = None
                await db.commit()
        return True

    now = datetime.now(timezone.utc)
    async with async_session() as db:
        created = 0
        pending_doc_ids: list[str] = []
        for r in results:
            # Re-query the page in THIS session (pages rows belong to the
            # claim session, which is closed by now).
            page = (
                await db.execute(
                    select(CrawlPage).where(
                        CrawlPage.source_id == source_id,
                        CrawlPage.url == r.url,
                    )
                )
            ).scalar_one_or_none()
            if r.status == "failed":
                if page is not None:
                    page.status = CrawlPage.STATUS_FAILED
                    page.error = (r.error or "")[:2000]
                    page.fetched_at = now
                    page.updated_at = now
                continue
            if r.status == "unchanged":
                if page is not None:
                    page.status = CrawlPage.STATUS_UNCHANGED
                    page.http_etag = r.etag or page.http_etag
                    page.http_last_modified = r.last_modified or page.http_last_modified
                    page.fetched_at = now
                    page.updated_at = now
                continue
            # crawled
            doc_id = await _upsert_scrape_document(
                db, databank_id, user_id, r.url, r.markdown,
                lang=r.lang, variant_group=variant_group(r.url), title=r.title,
            )
            if doc_id:
                created += 1
                pending_doc_ids.append(doc_id)
            if page is not None:
                page.status = CrawlPage.STATUS_CRAWLED
                page.title = r.title or page.title
                page.content_hash = r.content_hash
                # Language: URL prefix is authoritative (mirrors the site's
                # hreflang intent); detected script only fills unprefixed URLs.
                page.lang = path_lang(r.url) or r.lang or page.lang
                page.variant_group = variant_group(r.url)
                page.word_count = r.word_count
                page.http_etag = r.etag or page.http_etag
                page.http_last_modified = r.last_modified or page.http_last_modified
                page.fetched_at = now
                page.error = None
                page.updated_at = now

        done = (
            await db.execute(select(CrawlSource).where(CrawlSource.id == source_id))
        ).scalar_one_or_none()
        if done is not None:
            done.last_status = CrawlSource.STATUS_SUCCESS
            done.last_sync_at = now
            done.next_sync_at = (
                now + timedelta(minutes=done.sync_interval_minutes)
                if done.sync_enabled
                else None
            )
            await db.commit()
        # Queue ingest for new/changed pages so they're chunked + indexed
        # (otherwise documents stay "pending" forever and search stays empty).
        queued = await _queue_ingest_for_docs(db, databank_id, user_id, pending_doc_ids)
        logger.info(
            "Crawl source %s: %d docs created (%d queued for ingest) from %d pages",
            source_id, created, queued, len(results),
        )
        return True


async def _process_pending_scrape() -> None:
    """Claim and run one pending crawl job (single page or same-domain BFS)."""
    import hashlib
    import os
    import uuid

    from ...config import settings

    async with async_session() as db:
        result = await db.execute(
            select(ScrapeJob).where(ScrapeJob.status == "pending").order_by(ScrapeJob.created_at).limit(1)
        )
        job = result.scalar_one_or_none()
        if not job:
            return
        job.status = "running"
        await db.commit()
        job_id, databank_id, user_id = job.id, job.databank_id, job.user_id
        start_url, crawl_mode, max_pages = job.url, job.crawl_mode, max(1, min(job.max_pages, 500))

    scope = "single" if crawl_mode == "single" else "subtree"
    try:
        results = await asyncio.get_event_loop().run_in_executor(
            None, crawl_site, start_url, scope, max_pages
        )
    except Exception as e:
        logger.exception("Scrape job %s failed", job_id)
        async with async_session() as db:
            result = await db.execute(select(ScrapeJob).where(ScrapeJob.id == job_id))
            failed = result.scalar_one_or_none()
            if failed:
                failed.status = "failed"
                failed.error = str(e)[:2000]
                await db.commit()
        return

    async with async_session() as db:
        created = 0
        unchanged = 0
        pending_doc_ids: list[str] = []
        for r in results:
            if r.status == "unchanged":
                unchanged += 1
                continue
            if r.status != "crawled" or not r.markdown.strip():
                continue
            doc_id = await _upsert_scrape_document(
                db, databank_id, user_id, r.url, r.markdown,
                lang=r.lang, variant_group=variant_group(r.url), title=r.title,
            )
            if doc_id:
                created += 1
                pending_doc_ids.append(doc_id)
        result = await db.execute(select(ScrapeJob).where(ScrapeJob.id == job_id))
        done = result.scalar_one_or_none()
        if done:
            done.status = "completed"
            done.pages_found = created
            await db.commit()
        queued = await _queue_ingest_for_docs(db, databank_id, user_id, pending_doc_ids)
        logger.info(
            "Scrape job %s: %d created (%d queued for ingest), %d unchanged from %s",
            job_id, created, queued, unchanged, start_url,
        )


async def _upsert_scrape_document(
    db, databank_id: str, user_id: str, url: str, markdown: str,
    *, lang: str | None = None, variant_group: str | None = None,
    title: str | None = None,
) -> str | None:
    """Create or update one scrape document, deduping by (databank, url).

    Fixes the duplicate-document bug: the old crawler inserted a new Document
    row on every run, so re-crawling a site doubled its rows. Now an existing
    row for the same URL is updated in place; identical content is skipped
    entirely, changed content is re-stored and re-marked pending for ingest.

    ``lang``/``variant_group`` feed the EN/AR variant pairing (Phase A);
    ``title`` and the structured extraction (Phase B) land in ``doc.meta``.
    Returns the document id when new/changed content needs ingest, else None.
    """
    import hashlib
    import uuid

    from ...core.storage import put_doc

    content = markdown.encode("utf-8")
    digest = hashlib.sha256(content).hexdigest()

    existing = (
        await db.execute(
            select(Document).where(
                Document.databank_id == databank_id,
                Document.user_id == user_id,
                Document.source_type == "scrape",
                Document.source_url == url,
            )
        )
    ).scalars().all()

    if existing:
        doc = existing[0]
        if doc.content_hash == digest:
            return None  # unchanged — no new work
        doc.content_hash = digest
        doc.size_bytes = len(content)
        doc.status = "pending"
        doc.chunk_count = 0
        doc.error = None
        doc.filename = url[:500]
        if lang:
            doc.lang = lang
        if variant_group:
            doc.variant_group = variant_group
        doc.meta = build_structured_doc(url, title, markdown, lang)
        await db.flush()
        put_doc(databank_id, f"{doc.id}.md", content)
        return doc.id

    structured = build_structured_doc(url, title, markdown, lang)
    doc = Document(
        id=str(uuid.uuid4()),
        databank_id=databank_id,
        user_id=user_id,
        filename=url[:500],
        source_type="scrape",
        source_url=url[:2000],
        file_type="md",
        size_bytes=len(content),
        status="pending",
        content_hash=digest,
        lang=lang,
        variant_group=variant_group,
        meta=structured,
    )
    db.add(doc)
    await db.flush()
    put_doc(databank_id, f"{doc.id}.md", content)
    return doc.id


async def _queue_ingest_for_docs(
    db, databank_id: str, user_id: str, doc_ids: list[str]
) -> int:
    """Queue ingest jobs for crawled documents so they actually get indexed.

    The crawl only stores pending Documents; without ingest jobs they would
    never be chunked/embedded and the UI would show 0 processed forever.
    Returns the number of jobs queued.
    """
    import uuid

    if not doc_ids:
        return 0

    queued = 0
    for doc_id in doc_ids:
        job = IngestJob(
            id=str(uuid.uuid4()),
            user_id=user_id,
            databank_id=databank_id,
            document_id=doc_id,
            job_type="scrape",
            status="queued",
            progress=0,
        )
        db.add(job)
        await db.flush()
        await enqueue_job(str(job.id))
        queued += 1
    await db.commit()
    return queued




import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update

from ...database import async_session
from .cache import set_progress
from .chunker import chunk_text
from .embeddings import get_embedding_provider
from .models import Document, DocumentChunk, IngestJob, ScrapeJob

logger = logging.getLogger(__name__)

SEMAPHORE = asyncio.Semaphore(4)
_worker_task: asyncio.Task | None = None
_running = False


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
            await asyncio.sleep(2)


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
            except Exception as e:
                logger.exception("Job %s failed", job_id)
                job.status = "failed"
                job.error = str(e)[:2000]
                job.stage = "Failed"
                await db.commit()
                await set_progress(job_id, job.progress, "Failed")


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

    chunks = chunk_text(text_content)

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

    chunks = chunk_text(text_content)

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

    try:
        pages = await asyncio.get_event_loop().run_in_executor(
            None, _crawl_sync, start_url, crawl_mode, max_pages
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
        for url, text in pages:
            if not text.strip():
                continue
            content = text.encode("utf-8")
            doc = Document(
                id=str(uuid.uuid4()),
                databank_id=databank_id,
                user_id=user_id,
                filename=url[:500],
                source_type="scrape",
                source_url=url[:2000],
                file_type="txt",
                size_bytes=len(content),
                status="pending",
                content_hash=hashlib.sha256(content).hexdigest(),
            )
            db.add(doc)
            await db.flush()
            upload_dir = os.path.join(settings.UPLOAD_DIR, databank_id)
            os.makedirs(upload_dir, exist_ok=True)
            with open(os.path.join(upload_dir, f"{doc.id}.txt"), "wb") as f:
                f.write(content)
            created += 1
        result = await db.execute(select(ScrapeJob).where(ScrapeJob.id == job_id))
        done = result.scalar_one_or_none()
        if done:
            done.status = "completed"
            done.pages_found = created
            await db.commit()
        logger.info("Scrape job %s: %d documents from %s", job_id, created, start_url)


def _crawl_sync(start_url: str, crawl_mode: str, max_pages: int) -> list[tuple[str, str]]:
    """Blocking crawl: fetch + trafilatura extract. Same-domain BFS for full mode."""
    import trafilatura
    from html.parser import HTMLParser
    from urllib.parse import urljoin, urlparse
    from urllib.request import Request, urlopen

    class _Links(HTMLParser):
        def __init__(self):
            super().__init__()
            self.links: list[str] = []

        def handle_starttag(self, tag, attrs):
            if tag == "a":
                for k, v in attrs:
                    if k == "href" and v:
                        self.links.append(v)

    def _fetch(url: str) -> str:
        req = Request(url, headers={"User-Agent": "SayvorsBot/1.0"})
        with urlopen(req, timeout=20) as resp:  # noqa: S310
            return resp.read().decode("utf-8", errors="ignore")

    base_netloc = urlparse(start_url).netloc
    seen: set[str] = set()
    queue = [start_url]
    pages: list[tuple[str, str]] = []
    depth = 1 if crawl_mode == "single" else max_pages

    while queue and len(pages) < max_pages and len(seen) < max_pages:
        url = queue.pop(0)
        if url in seen:
            continue
        seen.add(url)
        try:
            html = _fetch(url)
        except Exception:
            continue
        text = trafilatura.extract(html) or ""
        if text.strip():
            pages.append((url, text))
        if crawl_mode == "full" and len(pages) < depth:
            parser = _Links()
            try:
                parser.feed(html)
            except Exception:
                continue
            for link in parser.links:
                full = urljoin(url, link).split("#")[0]
                if urlparse(full).netloc == base_netloc and full not in seen:
                    queue.append(full)
    return pages

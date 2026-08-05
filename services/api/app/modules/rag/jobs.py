import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ...database import async_session
from .cache import set_progress
from .chunker import chunk_text
from .embeddings import get_embedding_provider
from .models import Document, DocumentChunk, IngestJob

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
            await asyncio.sleep(2)


async def _dequeue_job() -> str | None:
    # Try Redis first
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
            result = await db.execute(
                select(IngestJob).where(IngestJob.id == job_id)
            )
            job = result.scalar_one_or_none()
            if not job:
                return

            # If already claimed (parsing), skip the status update
            if job.status != "parsing":
                job.status = "parsing"
                job.progress = 0
                job.stage = "Starting..."
                await db.commit()
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

    embed_progress = base_progress + (doc_progress * 2) // 3
    job.stage = f"Embedding {doc.filename}..."
    job.progress = embed_progress
    await db.commit()
    await set_progress(str(job.id), embed_progress, job.stage)

    await _embed_and_store(doc, chunks, job)

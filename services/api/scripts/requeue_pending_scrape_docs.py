"""One-time recovery: queue ingest jobs for scraped Documents stuck in
"pending" (crawled before the worker started queueing ingest jobs).

Run from services/api with the worker running (or afterwards) so the queued
jobs are picked up and the documents get chunked/embedded:

    python scripts/requeue_pending_scrape_docs.py
"""
import asyncio
import uuid

from sqlalchemy import select

from app.database import async_session
from app.modules.rag.cache import QUEUE_KEY
from app.modules.rag.models import Document, IngestJob


async def main() -> None:
    async with async_session() as db:
        docs = (
            await db.execute(
                select(Document).where(
                    Document.source_type == "scrape",
                    Document.status == "pending",
                )
            )
        ).scalars().all()
        print(f"pending scrape docs: {len(docs)}")

        queued = 0
        for doc in docs:
            job = IngestJob(
                id=str(uuid.uuid4()),
                user_id=doc.user_id,
                databank_id=doc.databank_id,
                document_id=doc.id,
                job_type="scrape",
                status="queued",
                progress=0,
            )
            db.add(job)
            await db.flush()
            from app.modules.rag.jobs import enqueue_job

            await enqueue_job(str(job.id))
            queued += 1
        await db.commit()
        print(f"queued ingest jobs: {queued}")


asyncio.run(main())

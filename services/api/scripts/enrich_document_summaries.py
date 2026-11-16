"""Backfill/enrichment runner (§31 Phase C): LLM-polish scraped page summaries.

Iterates scraped documents that have no ``meta.enriched_at`` yet and enriches
them one at a time (the module semaphore bounds LLM concurrency). Resumable:
re-run it and only the not-yet-enriched pages are billed again.

Requires RAG_AI_SUMMARY_ENABLED=true and an enabled tenant LLM model:

    python scripts/enrich_document_summaries.py
"""
import asyncio
import uuid

from sqlalchemy import select

from app.config import settings
from app.database import async_session
from app.modules.rag.models import Document
from app.modules.rag.summarizer import enrich_document


async def main() -> None:
    if not settings.RAG_AI_SUMMARY_ENABLED:
        print("RAG_AI_SUMMARY_ENABLED is false — nothing to do")
        return

    async with async_session() as db:
        docs = (
            await db.execute(
                select(Document.id).where(Document.source_type == "scrape")
            )
        ).scalars().all()

    enriched = 0
    skipped = 0
    failed = 0
    for doc_id in docs:
        result = await enrich_document(doc_id)
        if result:
            enriched += 1
        elif result is False:
            # enrich_document folds "already enriched" and "failed" into
            # False; distinguish by reading the marker afterwards.
            async with async_session() as db:
                meta = (
                    await db.execute(
                        select(Document.meta).where(Document.id == doc_id)
                    )
                ).scalar_one_or_none()
            if meta and meta.get("enriched_at"):
                skipped += 1
            else:
                failed += 1
        print(f"[{enriched + skipped + failed}/{len(docs)}] {doc_id}: "
              f"{'enriched' if result else 'skipped/failed'}")

    print(f"done: enriched={enriched} already/other={skipped} failed={failed}")


asyncio.run(main())

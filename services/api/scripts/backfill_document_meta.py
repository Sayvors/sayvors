"""One-time backfill: compute documents.meta (structured extraction, Phase B)
for scraped documents crawled before this shipped.

Reads each document's markdown from storage (no re-crawl, no network) and
stores summary/intent/sections/entities. Existing chunks keep their current
shape; they gain section metadata the next time the page changes and is
re-ingested.

Run from services/api:

    python scripts/backfill_document_meta.py
"""
import asyncio

from sqlalchemy import select

from app.core.storage import get_doc
from app.database import async_session
from app.modules.rag.document_structure import build_structured_doc
from app.modules.rag.models import Document


async def main() -> None:
    async with async_session() as db:
        docs = (
            await db.execute(
                select(Document).where(
                    Document.source_type == "scrape",
                    Document.meta.is_(None),
                )
            )
        ).scalars().all()
        print(f"scrape docs without meta: {len(docs)}")

        filled = 0
        skipped = 0
        for doc in docs:
            if not doc.source_url:
                skipped += 1
                continue
            try:
                content = get_doc(doc.databank_id, f"{doc.id}.{doc.file_type}")
                markdown = content.decode("utf-8", errors="ignore")
            except FileNotFoundError:
                skipped += 1
                continue
            doc.meta = build_structured_doc(
                doc.source_url, None, markdown, doc.lang
            )
            filled += 1
        await db.commit()
        print(f"meta filled: {filled}, skipped (no file/url): {skipped}")


asyncio.run(main())

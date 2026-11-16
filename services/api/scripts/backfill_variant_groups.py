"""One-time backfill: populate crawl_pages/documents variant_group + lang.

Covers rows created before the Phase A migration (20261116090000). Computes
the language-neutral variant identity from the URL path (crawler.variant_group)
and the language from the /en|/ar path prefix, falling back to the already
stored detected language on crawl_pages.

Run from services/api:

    python scripts/backfill_variant_groups.py
"""
import asyncio
import uuid

from sqlalchemy import select

from app.database import async_session
from app.modules.rag.models import CrawlPage, Document
from app.modules.rag.crawler import path_lang, variant_group


async def main() -> None:
    async with async_session() as db:
        pages = (
            await db.execute(
                select(CrawlPage).where(CrawlPage.variant_group.is_(None))
            )
        ).scalars().all()
        for p in pages:
            p.variant_group = variant_group(p.url)
            p.lang = path_lang(p.url) or p.lang
        await db.flush()
        print(f"crawl_pages backfilled: {len(pages)}")

        docs = (
            await db.execute(
                select(Document).where(
                    Document.variant_group.is_(None),
                    Document.source_type == "scrape",
                )
            )
        ).scalars().all()
        for d in docs:
            if not d.source_url:
                continue
            d.variant_group = variant_group(d.source_url)
            d.lang = path_lang(d.source_url) or d.lang
        await db.flush()
        print(f"documents backfilled: {len(docs)}")

        await db.commit()


asyncio.run(main())

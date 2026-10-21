"""Backfill pgvector embeddings for existing databank chunks (safe to re-run).

The pgvector column (``document_chunks.embedding_vector``) is new, so every
chunk stored before the migration has a NULL vector and is invisible to the
vector side of the search. This script re-embeds those chunks with the
currently configured embedding provider and writes both the vector column and
the legacy JSON column.

Default is a dry-run report, exactly like ``scripts/dedupe_channels.py``:
nothing is written unless ``--apply`` is passed.

Usage (from services/api, venv active):
    python scripts/backfill_embeddings.py                        # dry-run report
    python scripts/backfill_embeddings.py --apply                # backfill all
    python scripts/backfill_embeddings.py --apply --databank-id <id>
    python scripts/backfill_embeddings.py --apply --force        # re-embed all
    python scripts/backfill_embeddings.py --apply --limit 500     # cap the run
"""
import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from sqlalchemy import func, select, update

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import async_session  # noqa: E402
from app.modules.rag.embeddings import (  # noqa: E402
    canonical_vector,
    get_embedding_provider,
)
from app.modules.rag.models import DocumentChunk  # noqa: E402

logger = logging.getLogger("backfill_embeddings")

# Chunks embedded per provider request. Small enough to stay under a
# provider's per-request token limit, large enough to be worth the round trip.
EMBED_BATCH = 32
# Rows written per transaction.
COMMIT_EVERY = 200


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="write the vectors (without it, this is a report only)",
    )
    parser.add_argument(
        "--databank-id",
        default=None,
        help="only backfill one databank",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="re-embed chunks that already have a vector",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="stop after this many chunks (0 = no limit)",
    )
    return parser.parse_args()


async def _report(db, databank_id: str | None, force: bool) -> int:
    query = select(func.count()).select_from(DocumentChunk)
    if databank_id:
        query = query.where(DocumentChunk.databank_id == databank_id)
    if not force:
        query = query.where(DocumentChunk.embedding_vector.is_(None))
    pending = int((await db.execute(query)).scalar_one() or 0)

    by_model = select(
        DocumentChunk.embedding_model,
        func.count(),
    ).group_by(DocumentChunk.embedding_model)
    if databank_id:
        by_model = by_model.where(DocumentChunk.databank_id == databank_id)
    rows = (await db.execute(by_model)).fetchall()

    print(f"chunks to embed : {pending}")
    print("stored vectors by model:")
    for model, count in rows:
        print(f"  {model or 'unknown':45s} {count}")
    return pending


async def _backfill(db, databank_id: str | None, force: bool, limit: int) -> int:
    provider = await get_embedding_provider()
    model_tag = provider.model_tag
    print(f"embedding model : {model_tag}")

    query = select(DocumentChunk).order_by(DocumentChunk.id)
    if databank_id:
        query = query.where(DocumentChunk.databank_id == databank_id)
    if not force:
        query = query.where(DocumentChunk.embedding_vector.is_(None))
    if limit:
        query = query.limit(limit)

    done = 0
    pending: list[DocumentChunk] = []
    async for chunk in (await db.stream(query)).scalars():
        pending.append(chunk)
        if len(pending) < EMBED_BATCH:
            continue
        done += await _flush(db, pending, provider, model_tag)
        pending = []
    if pending:
        done += await _flush(db, pending, provider, model_tag)
    return done


async def _flush(db, chunks: list[DocumentChunk], provider, model_tag: str) -> int:
    vectors = await provider.embed([chunk.content for chunk in chunks])
    written = 0
    for chunk, vector in zip(chunks, vectors):
        canonical = canonical_vector(vector)
        if canonical is None:
            continue
        await db.execute(
            update(DocumentChunk)
            .where(DocumentChunk.id == chunk.id)
            .values(
                embedding=json.dumps(canonical),
                embedding_vector=canonical,
                embedding_model=model_tag,
            )
        )
        written += 1
    await db.commit()
    print(f"  embedded {written} chunks (running total unknown after commit)")
    return written


async def main() -> int:
    args = _parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    async with async_session() as db:
        pending = await _report(db, args.databank_id, args.force)
        if not args.apply:
            print("\nDry run. Re-run with --apply to write the vectors.")
            return 0
        if pending == 0 and not args.force:
            print("\nNothing to do.")
            return 0
        print()
        await _backfill(db, args.databank_id, args.force, args.limit)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

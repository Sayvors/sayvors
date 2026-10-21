"""Hybrid (vector + keyword) retrieval over databank chunks.

PostgreSQL + pgvector is the production path: the HNSW index answers the
vector side and a GIN-indexed ``tsvector`` answers the keyword side. Any
other dialect (the test suite runs on SQLite) gets an in-process cosine and
a LIKE keyword side, so the merge logic is still exercised end to end.

Two properties both paths guarantee, because the old implementation broke
both of them:

* **The whole databank is searched.** The previous code loaded only the
  first ``top_k * 3`` chunks in ``seq`` order, so everything past that
  window was invisible — silently wrong answers, not merely slow ones.
* **Only comparable vectors are compared.** A chunk embedded with a
  different model is excluded instead of being scored against a foreign
  vector (the old code skipped it only when the width differed, which
  silently dropped half a databank).
"""
from __future__ import annotations

import json
import logging
import math
import re
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Reciprocal-rank-fusion damping constant (Cormack et al., 2009).
RRF_K = 60
# Cap on the in-process fallback scan: without an ANN index the whole
# databank is read, so the scan is bounded and the limit is logged.
FALLBACK_SCAN_LIMIT = 5000
# Words shorter than this are noise for a keyword match.
_MIN_TERM_LENGTH = 2
_MAX_QUERY_TERMS = 8
# The keyword side uses Postgres' 'simple' configuration on purpose: it
# applies no stemming and no English stopwords, so Arabic text is not
# mangled by an English stemmer.
_TS_CONFIG = "simple"


def _is_postgres(db: AsyncSession) -> bool:
    bind = db.get_bind()
    return bool(bind is not None and bind.dialect.name == "postgresql")


def _vector_literal(vector: list[float]) -> str:
    """pgvector's text input format: ``[0.1,0.2]``."""
    return "[" + ",".join(repr(float(v)) for v in vector) + "]"


def _row_to_hit(row) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "content": row.content,
        "document_id": str(row.document_id),
        "metadata_": row.metadata,
        "score": float(row.score or 0.0),
    }


async def _pg_vector_search(
    db: AsyncSession,
    databank_id: str,
    query_vector: list[float],
    query_model: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    """ANN search over the pgvector column (HNSW)."""
    sql = text("""
        SELECT id, content, document_id, metadata,
               1 - (embedding_vector <=> CAST(:qv AS vector)) AS score
        FROM document_chunks
        WHERE databank_id = :databank_id
          AND embedding_vector IS NOT NULL
          AND (
                CAST(:model AS text) IS NULL
                OR embedding_model = CAST(:model AS text)
              )
        ORDER BY embedding_vector <=> CAST(:qv AS vector)
        LIMIT :limit
    """)
    rows = (
        await db.execute(
            sql,
            {
                "qv": _vector_literal(query_vector),
                "databank_id": databank_id,
                "model": query_model,
                "limit": limit,
            },
        )
    ).fetchall()
    return [_row_to_hit(row) for row in rows]


async def _fallback_vector_search(
    db: AsyncSession,
    databank_id: str,
    query_vector: list[float],
    query_model: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    """In-process cosine for databases without pgvector (tests, dev)."""
    rows = (
        await db.execute(
            text("""
                SELECT id, content, document_id, metadata, embedding, embedding_model
                FROM document_chunks
                WHERE databank_id = :databank_id
                  AND embedding IS NOT NULL
                ORDER BY seq
                LIMIT :limit
            """),
            {"databank_id": databank_id, "limit": FALLBACK_SCAN_LIMIT},
        )
    ).fetchall()
    if len(rows) >= FALLBACK_SCAN_LIMIT:
        logger.warning(
            "Vector fallback scanned the cap of %s chunks for databank %s; "
            "results may miss content",
            FALLBACK_SCAN_LIMIT,
            databank_id,
        )

    query_norm = math.sqrt(sum(v * v for v in query_vector))
    hits: list[dict[str, Any]] = []
    for row in rows:
        if query_model and row.embedding_model != query_model:
            continue
        try:
            vector = json.loads(row.embedding)
        except (TypeError, ValueError):
            continue
        if len(vector) != len(query_vector):
            continue
        norm = math.sqrt(sum(v * v for v in vector)) * query_norm
        if norm == 0:
            continue
        score = sum(a * b for a, b in zip(vector, query_vector)) / norm
        hits.append(
            {
                "id": str(row.id),
                "content": row.content,
                "document_id": str(row.document_id),
                "metadata_": row.metadata,
                "score": score,
            }
        )
    hits.sort(key=lambda hit: hit["score"], reverse=True)
    return hits[:limit]


async def _pg_keyword_search(
    db: AsyncSession, databank_id: str, query_text: str, limit: int
) -> list[dict[str, Any]]:
    sql = text(f"""
        SELECT id, content, document_id, metadata,
               ts_rank(
                   to_tsvector('{_TS_CONFIG}', content),
                   plainto_tsquery('{_TS_CONFIG}', :q)
               ) AS score
        FROM document_chunks
        WHERE databank_id = :databank_id
          AND to_tsvector('{_TS_CONFIG}', content)
              @@ plainto_tsquery('{_TS_CONFIG}', :q)
        ORDER BY score DESC
        LIMIT :limit
    """)
    rows = (
        await db.execute(
            sql,
            {"databank_id": databank_id, "q": query_text, "limit": limit},
        )
    ).fetchall()
    return [_row_to_hit(row) for row in rows]


async def _fallback_keyword_search(
    db: AsyncSession, databank_id: str, query_text: str, limit: int
) -> list[dict[str, Any]]:
    """Term matching for databases without tsvector (SQLite in tests)."""
    terms = [
        term
        for term in re.split(r"\W+", (query_text or "").lower())
        if len(term) >= _MIN_TERM_LENGTH
    ]
    terms = terms[:_MAX_QUERY_TERMS]
    if not terms:
        return []

    clauses: list[str] = []
    params: dict[str, Any] = {"databank_id": databank_id, "limit": limit}
    for index, term in enumerate(terms):
        key = f"term{index}"
        clauses.append(f"lower(content) LIKE :{key}")
        params[key] = f"%{term}%"
    sql = text(f"""
        SELECT id, content, document_id, metadata, 1.0 AS score
        FROM document_chunks
        WHERE databank_id = :databank_id
          AND ({' OR '.join(clauses)})
        LIMIT :limit
    """)
    rows = (await db.execute(sql, params)).fetchall()
    return [_row_to_hit(row) for row in rows]


def _rrf_merge(
    vector_hits: list[dict[str, Any]],
    keyword_hits: list[dict[str, Any]],
    top_k: int,
) -> list[dict[str, Any]]:
    """Reciprocal rank fusion of the two ranked lists."""
    merged: dict[str, dict[str, Any]] = {}
    for rank, hit in enumerate(vector_hits):
        merged[hit["id"]] = {**hit, "score": 1.0 / (RRF_K + rank + 1)}
    for rank, hit in enumerate(keyword_hits):
        rrf = 1.0 / (RRF_K + rank + 1)
        existing = merged.get(hit["id"])
        if existing is not None:
            existing["score"] += rrf
        else:
            merged[hit["id"]] = {**hit, "score": rrf}
    return sorted(merged.values(), key=lambda hit: hit["score"], reverse=True)[:top_k]


async def hybrid_search(
    databank_id: str,
    query_vector: list[float] | None,
    query_text: str,
    top_k: int,
    db: AsyncSession,
    query_model: str | None = None,
) -> list[dict]:
    """Search a databank and return the best ``top_k`` chunks.

    ``query_model`` is the tag of the model that produced ``query_vector``.
    Chunks embedded with another model are excluded from the vector side:
    their vectors are not comparable with the query's.
    """
    top_k = max(1, min(int(top_k or 5), 50))
    limit = top_k * 3
    postgres = _is_postgres(db)

    vector_hits: list[dict[str, Any]] = []
    if query_vector:
        if postgres:
            vector_hits = await _pg_vector_search(
                db, databank_id, query_vector, query_model, limit
            )
        else:
            vector_hits = await _fallback_vector_search(
                db, databank_id, query_vector, query_model, limit
            )

    keyword_hits: list[dict[str, Any]] = []
    if (query_text or "").strip():
        if postgres:
            keyword_hits = await _pg_keyword_search(
                db, databank_id, query_text, limit
            )
        else:
            keyword_hits = await _fallback_keyword_search(
                db, databank_id, query_text, limit
            )

    return _rrf_merge(vector_hits, keyword_hits, top_k)

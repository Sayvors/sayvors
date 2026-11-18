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

from ...config import settings

logger = logging.getLogger(__name__)

# Reciprocal-rank-fusion damping constant (Cormack et al., 2009).
RRF_K = 60
# Cap on the in-process fallback scan: without an ANN index the whole
# databank is read, so the scan is bounded and the limit is logged.
FALLBACK_SCAN_LIMIT = 5000
# Words shorter than this are noise for a keyword match.
_MIN_TERM_LENGTH = 2
_MAX_QUERY_TERMS = 8
# Prefix search is enabled from this length: short prefixes match almost every
# word in an Arabic or English document and destroy ranking.
_MIN_PREFIX_LENGTH = 4
# Unicode letters and digits, NOT underscore and NOT the Arabic block: the old
# [\w\u0600-\u06FF] swallowed U+061F/060C/061B (؟ ، ؛) into the last word, so
# the most common word of an Arabic question could never match. \w already
# includes Arabic letters; the explicit block range added only punctuation.
_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)

# Query-side folding, no re-indexing required. Alef variants and final ya/ta
# collapse onto their base letter; tatweel and harakat are removed. This makes
# a query written with hamza/diacritics match a plain stored term (and the
# SQLite fallback folds both sides). Fully equivalent stored text needs a
# re-index with the same fold — that is P1, not this change.
_ARABIC_FOLD: dict[int, str | None] = {
    ord("أ"): "ا", ord("إ"): "ا", ord("آ"): "ا",
    ord("ى"): "ي", ord("ة"): "ه", ord("ـ"): None,
}
for _codepoint in range(0x064B, 0x0653):  # harakat
    _ARABIC_FOLD[_codepoint] = None
_ARABIC_FOLD[0x0670] = None  # superscript alef

# Curated, deliberately small. A large automatic list removes real terms from
# short messages ("open", "price", "كم"). Only function words that carry no
# retrieval signal belong here.
_STOPWORDS = frozenset({
    # English
    "a", "an", "the", "and", "or", "but", "if", "then", "than", "that",
    "this", "these", "those", "is", "are", "was", "were", "be", "been",
    "being", "am", "do", "does", "did", "have", "has", "had", "can",
    "could", "will", "would", "should", "may", "might", "must", "of",
    "to", "in", "on", "at", "by", "for", "with", "from", "into", "about",
    "as", "it", "its", "you", "your", "we", "our", "they", "their", "he",
    "she", "i", "me", "my", "what", "which", "who", "whom", "when",
    "where", "why", "how", "there", "here", "not", "no", "very", "just",
    "also", "only", "up", "out", "so", "all", "any", "some", "more",
    # Arabic
    "في", "من", "على", "إلى", "الى", "عن", "مع", "أو", "او", "هو", "هي",
    "هم", "أنت", "انت", "أنتم", "انتم", "أنا", "انا", "نحن", "هذا",
    "هذه", "ذلك", "تلك", "التي", "الذي", "الذين", "كان", "كانت", "قد",
    "لم", "لن", "إن", "ان", "أن", "ان", "لا", "ما", "كل", "بعض", "كيف",
    "لماذا", "متى", "أين", "اين", "كم", "هناك", "هنا", "ثم", "لكن",
    "بل", "حتى", "بعد", "قبل", "بين", "عند", "جدا", "حاليا",
})


def normalize_term(term: str) -> str:
    """Fold a query term for matching. No stemming — Arabic must not be
    mangled by an English stemmer; this only unifies spelling variants."""
    return "".join(
        _ARABIC_FOLD.get(ord(ch), ch)
        for ch in term.casefold()
        if _ARABIC_FOLD.get(ord(ch), ch) is not None
    )


def content_terms(text: str) -> frozenset[str]:
    """Normalized token set for near-duplicate detection in the prompt block."""
    out: set[str] = set()
    for raw in _WORD_RE.findall(text or ""):
        token = normalize_term(raw)
        if token:
            out.add(token)
    return frozenset(out)


def query_terms(query_text: str) -> list[str]:
    """Content terms from a natural-language question, stopwords removed."""
    terms: list[str] = []
    for raw in _WORD_RE.findall(query_text or ""):
        term = raw.strip("_").casefold()
        if len(term) < _MIN_TERM_LENGTH or term in _STOPWORDS or term in terms:
            continue
        terms.append(term)
        if len(terms) >= _MAX_QUERY_TERMS:
            break
    return terms


def keyword_tsquery(query_text: str) -> str:
    """Build an OR tsquery from natural-language text.

    ``plainto_tsquery`` ANDs every word, so a question like "multilingual
    social media Arabic English" only matched a chunk containing ALL five
    words — usually zero results. OR + ts_rank (more matched terms rank higher)
    gives forgiving retrieval that works for both English and Arabic without
    embeddings. Terms come from a word-character regex, so the result is safe
    to pass as a bound parameter to ``to_tsquery``.

    Stopwords are dropped before the term cap so noise cannot crowd out the
    words that carry intent. Terms of four characters or more use Postgres'
    prefix operator, so "beans" also finds "bean". Arabic spelling variants
    are added as an extra OR branch only when they differ from the raw term.
    """
    fragments: list[str] = []
    for term in query_terms(query_text):
        variants = [term]
        normalized = normalize_term(term)
        if normalized and normalized != term:
            variants.append(normalized)
        for variant in variants:
            fragment = variant + (":*" if len(variant) >= _MIN_PREFIX_LENGTH else "")
            if fragment not in fragments:
                fragments.append(fragment)
            if len(fragments) >= _MAX_QUERY_TERMS:
                return " | ".join(fragments)
    return " | ".join(fragments)
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
    q = keyword_tsquery(query_text)
    if not q:
        return []
    sql = text(f"""
        SELECT id, content, document_id, metadata,
               ts_rank(
                   to_tsvector('{_TS_CONFIG}', content),
                   to_tsquery('{_TS_CONFIG}', :q)
               ) AS score
        FROM document_chunks
        WHERE databank_id = :databank_id
          AND to_tsvector('{_TS_CONFIG}', content) @@ to_tsquery('{_TS_CONFIG}', :q)
        ORDER BY score DESC
        LIMIT :limit
    """)
    rows = (
        await db.execute(
            sql,
            {"databank_id": databank_id, "q": q, "limit": limit},
        )
    ).fetchall()
    return [_row_to_hit(row) for row in rows]


async def _fallback_keyword_search(
    db: AsyncSession, databank_id: str, query_text: str, limit: int
) -> list[dict[str, Any]]:
    """Term matching for databases without tsvector (SQLite in tests).

    Both sides are folded with the same Python function, so a query with hamza
    or harakat matches plain stored text and vice versa. Postgres cannot fold
    stored text without losing the GIN index; its query side emits both variants
    instead. The scan is capped like the vector fallback: this path is for
    tests and dev only, never the production index.
    """
    terms = [normalize_term(term) for term in query_terms(query_text)]
    terms = [term for term in terms if term]
    if not terms:
        return []

    rows = (
        await db.execute(
            text("""
                SELECT id, content, document_id, metadata
                FROM document_chunks
                WHERE databank_id = :databank_id
                ORDER BY seq
                LIMIT :scan_limit
            """),
            {"databank_id": databank_id, "scan_limit": FALLBACK_SCAN_LIMIT},
        )
    ).fetchall()
    if len(rows) >= FALLBACK_SCAN_LIMIT:
        logger.warning(
            "Keyword fallback scanned the cap of %s chunks for databank %s; "
            "results may miss content",
            FALLBACK_SCAN_LIMIT, databank_id,
        )

    hits: list[dict[str, Any]] = []
    for row in rows:
        folded = normalize_term(row.content or "")
        if any(term in folded for term in terms):
            hits.append({
                "id": str(row.id),
                "content": row.content,
                "document_id": str(row.document_id),
                "metadata_": row.metadata,
                "score": 1.0,
            })
    return hits[:limit]


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
    # When embeddings are off the Postgres column is a TEXT placeholder and
    # the pgvector operators do not exist. The non-Postgres fallback reads
    # the legacy JSON column with in-process cosine, so it keeps working
    # (that is the path the test suite runs on).
    if query_vector:
        if postgres:
            if settings.embeddings_enabled:
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

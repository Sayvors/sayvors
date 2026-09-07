import json
import math
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors."""
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


async def hybrid_search(
    databank_id: str,
    query_vector: list[float] | None,
    query_text: str,
    top_k: int,
    db: AsyncSession,
) -> list[dict]:
    # 1. Load all chunks for this databank (with embeddings)
    load_sql = text("""
        SELECT id, content, document_id, metadata, embedding, embedding_model
        FROM document_chunks
        WHERE databank_id = :databank_id
          AND embedding IS NOT NULL
        ORDER BY seq
    """)
    result = await db.execute(load_sql, {"databank_id": databank_id})
    all_chunks = result.fetchall()

    # 2. Vector search — in-memory cosine similarity.
    # Rows embedded by a different model/dimensionality are skipped:
    # cross-dim cosine scores are meaningless, not just noisy.
    vector_scores: dict[str, float] = {}
    if query_vector:
        for row in all_chunks:
            if not row.embedding:
                continue
            try:
                chunk_vec = json.loads(row.embedding)
                if len(chunk_vec) != len(query_vector):
                    continue
                score = _cosine_similarity(query_vector, chunk_vec)
                vector_scores[str(row.id)] = score
            except (json.JSONDecodeError, TypeError):
                continue

    # 3. Keyword search — PostgreSQL tsvector full-text
    keyword_sql = text("""
        SELECT id, content, document_id, metadata,
               ts_rank(to_tsvector('english', content), plainto_tsquery('english', :query_text)) AS keyword_score
        FROM document_chunks
        WHERE databank_id = :databank_id
          AND to_tsvector('english', content) @@ plainto_tsquery('english', :query_text)
        ORDER BY keyword_score DESC
        LIMIT :limit
    """)
    keyword_result = await db.execute(
        keyword_sql,
        {"query_text": query_text, "databank_id": databank_id, "limit": top_k * 3},
    )
    keyword_rows = keyword_result.fetchall()

    keyword_scores: dict[str, float] = {}
    for rank, row in enumerate(keyword_rows):
        chunk_id = str(row.id)
        keyword_scores[chunk_id] = row.keyword_score or 1.0 / (60 + rank + 1)

    # 4. RRF merge
    k = 60
    scores: dict[str, dict] = {}
    chunk_map = {str(row.id): row for row in all_chunks}

    # Vector scores
    sorted_vector = sorted(vector_scores.items(), key=lambda x: x[1], reverse=True)
    for rank, (chunk_id, _) in enumerate(sorted_vector):
        rrf = 1 / (k + rank + 1)
        row = chunk_map.get(chunk_id)
        if row:
            scores[chunk_id] = {
                "id": chunk_id,
                "content": row.content,
                "document_id": str(row.document_id),
                "metadata_": row.metadata,
                "score": rrf,
            }

    # Keyword scores
    sorted_keyword = sorted(keyword_scores.items(), key=lambda x: x[1], reverse=True)
    for rank, (chunk_id, _) in enumerate(sorted_keyword):
        rrf = 1 / (k + rank + 1)
        if chunk_id in scores:
            scores[chunk_id]["score"] += rrf
        else:
            row = chunk_map.get(chunk_id)
            if row:
                scores[chunk_id] = {
                    "id": chunk_id,
                    "content": row.content,
                    "document_id": str(row.document_id),
                    "metadata_": row.metadata,
                    "score": rrf,
                }

    merged = sorted(scores.values(), key=lambda x: x["score"], reverse=True)
    return merged[:top_k]

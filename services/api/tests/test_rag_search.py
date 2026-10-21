"""RAG search: the whole databank is searched, and only comparable vectors score.

Two properties the old implementation broke are pinned here:

* **The prefix window.** It loaded only the first ``top_k * 3`` chunks in
  ``seq`` order, so anything past that window was invisible — silently
  wrong answers, not merely slow ones.
* **Comparable vectors only.** A chunk embedded with a different model must
  be excluded, not scored against a foreign vector.

These run on the in-process fallback path (the test suite is SQLite); the
PostgreSQL/pgvector path is covered by ``test_rag_pgvector.py``.
"""
import json

import pytest

from app.modules.rag.embeddings import CANONICAL_DIMENSIONS, canonical_vector
from app.modules.rag.models import Databank, Document, DocumentChunk
from app.modules.rag.search import hybrid_search

_BANK = "rag-search-bank-0001"
_USER = "rag-search-user-0001"
_DOC = "rag-search-doc-0001"
_MODEL = "test:embedder"
# A token that appears in no chunk, so only the vector side can match.
_ONLY_VECTOR = "zzquerytoken"


def _vector(*values: float) -> list[float]:
    """A canonical-width vector pointing along the given direction."""
    vector = [0.0] * CANONICAL_DIMENSIONS
    for index, value in enumerate(values):
        vector[index] = value
    return vector


async def _seed(db) -> None:
    db.add(Databank(id=_BANK, user_id=_USER, name="Search Bank"))
    db.add(
        Document(
            id=_DOC,
            databank_id=_BANK,
            user_id=_USER,
            filename="menu.txt",
            source_type="upload",
            file_type="txt",
            status="completed",
        )
    )
    await db.commit()


async def _add_chunk(
    db,
    chunk_id: str,
    *,
    content: str,
    seq: int,
    vector: list[float] | None = None,
    model: str = _MODEL,
) -> None:
    db.add(
        DocumentChunk(
            id=chunk_id,
            document_id=_DOC,
            databank_id=_BANK,
            content=content,
            embedding=json.dumps(vector) if vector else None,
            embedding_vector=vector,
            embedding_model=model if vector else "none",
            seq=seq,
            token_count=len(content.split()),
        )
    )


@pytest.mark.asyncio
async def test_search_finds_a_chunk_past_the_old_prefix_window(db):
    """Chunk 30 of 30 was invisible to the old implementation."""
    await _seed(db)
    for index in range(30):
        await _add_chunk(
            db,
            f"rag-chunk-{index:04d}",
            content=f"menu item {index} unrelated",
            seq=index,
            vector=_vector(0.0, 1.0),
        )
    await _add_chunk(
        db,
        "rag-chunk-match",
        content="the answer lives in the last chunk",
        seq=30,
        vector=_vector(1.0, 0.0),
    )
    await db.commit()

    results = await hybrid_search(
        databank_id=_BANK,
        query_vector=_vector(1.0, 0.0),
        query_text=_ONLY_VECTOR,
        top_k=3,
        db=db,
        query_model=_MODEL,
    )
    assert results, "search returned nothing"
    assert results[0]["id"] == "rag-chunk-match"


@pytest.mark.asyncio
async def test_keyword_hit_without_a_vector_is_still_returned(db):
    """A chunk stored while the embedding provider was down stays searchable."""
    await _seed(db)
    await _add_chunk(
        db,
        "rag-chunk-text",
        content="our best grilled seafood platter",
        seq=0,
    )
    await db.commit()

    results = await hybrid_search(
        databank_id=_BANK,
        query_vector=None,
        query_text="grilled seafood",
        top_k=3,
        db=db,
    )
    assert [hit["id"] for hit in results] == ["rag-chunk-text"]


@pytest.mark.asyncio
async def test_vector_hits_exclude_chunks_from_another_model(db):
    """Vectors from a different model are not comparable and are skipped."""
    await _seed(db)
    await _add_chunk(
        db,
        "rag-chunk-same",
        content="same model chunk",
        seq=0,
        vector=_vector(1.0, 0.0),
    )
    await _add_chunk(
        db,
        "rag-chunk-other",
        content="other model chunk",
        seq=1,
        vector=_vector(1.0, 0.0),
        model="other:embedder",
    )
    await db.commit()

    results = await hybrid_search(
        databank_id=_BANK,
        query_vector=_vector(1.0, 0.0),
        query_text=_ONLY_VECTOR,
        top_k=5,
        db=db,
        query_model=_MODEL,
    )
    ids = [hit["id"] for hit in results]
    assert "rag-chunk-same" in ids
    assert "rag-chunk-other" not in ids


def test_canonical_vector_rejects_a_wrong_width():
    """A provider that answers with another width must not be stored."""
    assert canonical_vector([0.1, 0.2]) is None
    assert canonical_vector(None) is None
    wide = _vector(1.0)
    assert canonical_vector(wide) == wide

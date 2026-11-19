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
from app.modules.rag.search import hybrid_search, keyword_tsquery

# ── Keyword query building (naive questions must still retrieve) ──

def test_keyword_tsquery_ors_terms_and_dedups():
    q = keyword_tsquery("multilingual social media Arabic English")
    assert "|" in q
    for term in ("multilingual", "social", "media", "arabic", "english"):
        assert term in q
    assert set(q.split(" | ")) == set(
        keyword_tsquery("Arabic, english multilingual social media").split(" | ")
    )  # dedup-invariant set


def test_keyword_tsquery_keeps_arabic_and_caps_terms():
    q = keyword_tsquery("مطعم البرجر في جدة potassium 1 2 3 4 5 6 7 8 9 10")
    assert "مطعم" in q
    assert "|" in q
    assert len(q.split("|")) <= 8


def test_keyword_tsquery_empty_for_symbols():
    assert keyword_tsquery("?! ...") == ""


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


# -- P0 query-side correctness ----------------------------------------------


def test_arabic_punctuation_is_no_longer_part_of_a_term():
    q = keyword_tsquery("كم سعر الشاورما؟")
    assert "؟" not in q
    assert "سعر" in q
    assert "الشاورما" in q


def test_arabic_spelling_variants_fold_to_the_same_term():
    from app.modules.rag.search import normalize_term

    assert normalize_term("أسعار") == normalize_term("اسعار") == "اسعار"
    assert normalize_term("الشاورمـة") == normalize_term("الشاورمة")
    plain = set(keyword_tsquery("اسعار الطعام").split(" | "))
    hamza = set(keyword_tsquery("أسعار الطعام").split(" | "))
    assert plain & hamza, "the two spellings must share at least one query term"


def test_stopwords_do_not_crowd_out_real_terms():
    q = keyword_tsquery("what is the price of the beans?")
    assert "what" not in q and "is" not in q and "the" not in q and "of" not in q
    assert "price:*" in q and "beans:*" in q


def test_long_terms_use_prefix_but_short_terms_do_not():
    q = keyword_tsquery("hi beans")
    assert "hi" in q
    assert "beans:*" in q


@pytest.mark.asyncio
async def test_near_duplicate_chunks_do_not_consume_top_k_slots(db):
    """Identical/near-identical passages must collapse before the top_k cut."""
    await _seed(db)
    await _add_chunk(db, "rag-dup-a", content="اللاتيه بـ15 ريال وكبير الحجم متوفر", seq=0)
    await _add_chunk(db, "rag-dup-b", content="اللاتيه بـ15 ريال وكبير الحجم متوفر اليوم", seq=1)
    await _add_chunk(db, "rag-distinct", content="Delivery inside Riyadh takes two days", seq=2)
    await db.commit()

    hits = await hybrid_search(
        databank_id=_BANK, query_vector=None,
        query_text="اللاتيه 15 ريال Delivery Riyadh two days", top_k=2, db=db,
    )
    ids = [hit["id"] for hit in hits]
    assert len(ids) == 2
    assert "rag-distinct" in ids, "a duplicate must not crowd out a distinct passage"
    assert not ({"rag-dup-a", "rag-dup-b"} <= set(ids))


@pytest.mark.asyncio
async def test_keyword_search_matches_hamza_query_to_plain_stored_text(db):
    """The SQLite fallback folds both sides; Postgres emits both variants."""
    await _seed(db)
    await _add_chunk(db, "rag-hamza-chunk", content="أسعار القهوة خمسون ريالا", seq=0)
    await db.commit()

    hits = await hybrid_search(
        databank_id=_BANK, query_vector=None, query_text="اسعار القهوة",
        top_k=5, db=db,
    )
    assert [hit["id"] for hit in hits] == ["rag-hamza-chunk"]

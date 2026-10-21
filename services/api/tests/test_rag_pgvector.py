"""pgvector integration: the real ANN path on PostgreSQL.

Skipped unless ``DATABASE_URL`` points at PostgreSQL that can create the
``vector`` extension. CI runs its postgres service from the pgvector image,
so this executes there; a local database without the extension skips.

The table is created in its own schema and the session's ``search_path`` is
pointed at it, so the test never touches the application schema.
"""
import os

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.modules.rag.embeddings import CANONICAL_DIMENSIONS
from app.modules.rag.search import hybrid_search

DATABASE_URL = os.environ.get("DATABASE_URL", "")
_SCHEMA = "pgvector_test"
_BANK = "pgvector-bank-0001"
_MODEL = "test:embedder"


def _vector(*values: float) -> list[float]:
    vector = [0.0] * CANONICAL_DIMENSIONS
    for index, value in enumerate(values):
        vector[index] = value
    return vector


def _literal(vector: list[float]) -> str:
    return "[" + ",".join(str(float(value)) for value in vector) + "]"


@pytest_asyncio.fixture
async def pg_session():
    if not DATABASE_URL.startswith("postgresql"):
        pytest.skip("DATABASE_URL is not PostgreSQL")

    engine = create_async_engine(DATABASE_URL)
    try:
        async with engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    except Exception as e:  # pragma: no cover - depends on the database
        await engine.dispose()
        pytest.skip(f"pgvector extension unavailable: {e}")

    async with engine.begin() as conn:
        await conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {_SCHEMA}"))
        await conn.execute(text(f"DROP TABLE IF EXISTS {_SCHEMA}.document_chunks"))
        await conn.execute(
            text(f"""
                CREATE TABLE {_SCHEMA}.document_chunks (
                    id text PRIMARY KEY,
                    document_id text NOT NULL,
                    databank_id text NOT NULL,
                    content text NOT NULL,
                    metadata jsonb,
                    embedding text,
                    embedding_model text,
                    embedding_vector vector({CANONICAL_DIMENSIONS})
                )
            """)
        )
        await conn.execute(
            text(
                f"CREATE INDEX ix_pgvector_test_hnsw ON {_SCHEMA}.document_chunks "
                "USING hnsw (embedding_vector vector_cosine_ops)"
            )
        )

    try:
        async with engine.connect() as conn:
            await conn.execute(text(f"SET search_path TO {_SCHEMA}, public"))
            async with AsyncSession(bind=conn) as session:
                yield session
    finally:
        async with engine.begin() as conn:
            await conn.execute(text(f"DROP SCHEMA IF EXISTS {_SCHEMA} CASCADE"))
        await engine.dispose()


@pytest.mark.asyncio
async def test_pgvector_orders_by_cosine_distance(pg_session):
    """The nearest vector wins, and a foreign model's vector is excluded."""
    await pg_session.execute(
        text("""
            INSERT INTO document_chunks
                (id, document_id, databank_id, content, metadata, embedding,
                 embedding_model, embedding_vector)
            VALUES
                ('near', 'doc', :bank, 'near chunk', NULL, NULL, :model,
                 CAST(:near AS vector)),
                ('mid', 'doc', :bank, 'mid chunk', NULL, NULL, :model,
                 CAST(:mid AS vector)),
                ('far', 'doc', :bank, 'far chunk', NULL, NULL, :model,
                 CAST(:far AS vector)),
                ('other-model', 'doc', :bank, 'other model chunk', NULL, NULL,
                 'other:embedder', CAST(:near AS vector))
        """),
        {
            "bank": _BANK,
            "model": _MODEL,
            "near": _literal(_vector(1.0, 0.0)),
            "mid": _literal(_vector(0.9, 0.1)),
            "far": _literal(_vector(0.0, 1.0)),
        },
    )
    await pg_session.commit()

    results = await hybrid_search(
        databank_id=_BANK,
        query_vector=_vector(1.0, 0.0),
        query_text="",
        top_k=3,
        db=pg_session,
        query_model=_MODEL,
    )
    ids = [hit["id"] for hit in results]
    assert ids[0] == "near"
    assert "mid" in ids
    assert "other-model" not in ids


@pytest.mark.asyncio
async def test_pg_keyword_search_matches_arabic(pg_session):
    """The keyword side must work on Arabic, not only on English."""
    await pg_session.execute(
        text("""
            INSERT INTO document_chunks
                (id, document_id, databank_id, content, metadata, embedding,
                 embedding_model, embedding_vector)
            VALUES
                ('arabic', 'doc', :bank, 'مطعم البرجر بجدة', NULL, NULL, 'none', NULL)
        """),
        {"bank": _BANK},
    )
    await pg_session.commit()

    results = await hybrid_search(
        databank_id=_BANK,
        query_vector=None,
        query_text="مطعم",
        top_k=5,
        db=pg_session,
    )
    assert [hit["id"] for hit in results] == ["arabic"]

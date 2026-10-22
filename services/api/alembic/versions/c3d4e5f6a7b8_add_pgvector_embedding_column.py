"""Store databank chunk embeddings in a pgvector column (D10).

The old schema kept embeddings as JSON text in ``document_chunks.embedding``
and scored them in Python over a prefix window of the first
``top_k * 3`` chunks. That was wrong twice: the search silently ignored
everything past the window, and a JSON list was written into a TEXT column,
so any database with a real embedding backend failed the write outright.

This migration adds the searchable representation:

* ``document_chunks.embedding_vector vector(1024)`` - one dimension for
  every provider (see ``rag.embeddings.CANONICAL_DIMENSIONS``).
* an HNSW index over it (``vector_cosine_ops``) for approximate nearest
  neighbour search.
* a GIN index over ``to_tsvector('simple', content)`` for the keyword side.
  'simple' applies no stemming and no English stopwords, which is what
  Arabic content needs.

Requirements, because a database without them cannot run the vector branch:

* PostgreSQL with the ``vector`` extension available (``CREATE EXTENSION
  vector``). AWS RDS supports pgvector on supported engine versions; the
  migration fails loudly rather than silently degrading to a JSON blob.
* pgvector >= 0.5 for HNSW.

``EMBEDDINGS_ENABLED=false`` (the default outside production, see
``Settings.embeddings_enabled``) takes the other branch: ``embedding_vector``
is created as TEXT so the ORM keeps working, keyword search gets its GIN
index, and a local PostgreSQL without the extension is not stuck on this
revision. Turning embeddings on later converts that placeholder in place.

Both indexes are built with ``CONCURRENTLY`` so the write path stays open on
a large table; that requires the autocommit block (same pattern as the
``post.delete`` enum migration). The legacy ``embedding`` text column is left
in place: it is still written with the same vector as JSON so a rollback to
the previous release still finds vectors, and it can be dropped once the
pgvector path has proven itself in production.
"""
from alembic import op

revision = "c3d4e5f6a7b8"
down_revision = "b0c1d2e3f4a5"
branch_labels = None
depends_on = None

VECTOR_DIM = 1024
EXTENSION = "vector"
HNSW_INDEX = "ix_document_chunks_embedding_vector_hnsw"
GIN_INDEX = "ix_document_chunks_content_gin"


def upgrade() -> None:
    from app.config import settings

    # `embedding_vector` is the searchable representation, and its type needs
    # pgvector. When embeddings are off (the default outside production) the
    # column is still created as TEXT so the ORM maps document_chunks
    # normally: ingest, databank listing and keyword-only search keep working
    # on a PostgreSQL without the extension, and the rest of the migration
    # chain is not blocked behind this one.
    if not settings.embeddings_enabled:
        op.execute(
            "ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS embedding_vector TEXT"
        )
        with op.get_context().autocommit_block():
            op.execute(
                f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {GIN_INDEX} "
                "ON document_chunks USING gin (to_tsvector('simple', content))"
            )
        return

    try:
        op.execute(f"CREATE EXTENSION IF NOT EXISTS {EXTENSION}")
    except Exception as e:
        raise RuntimeError(
            "EMBEDDINGS_ENABLED is on but pgvector is not available on this "
            "database, so the vector column cannot be created. Install the "
            "extension and re-run `alembic upgrade head`:\n"
            "  - Docker/Compose: use the `pgvector/pgvector:pg16` image\n"
            "  - AWS RDS: the engine version must support pgvector, then run "
            "`CREATE EXTENSION IF NOT EXISTS vector;` as an admin\n"
            "  - Windows/PostgreSQL: install the `windows-x64` build of "
            "pgvector into the server's share/extension and lib folders, "
            "restart the service, then run the CREATE EXTENSION above\n"
            "To run without pgvector instead, set EMBEDDINGS_ENABLED=false.\n"
            "See docs/database/migration-safety.md section 9."
        ) from e

    # A database that first ran this with embeddings disabled holds a TEXT
    # placeholder. Converting it is safe because the placeholder is only ever
    # written as NULL; the SQL is idempotent and a no-op on a fresh database.
    op.execute(
        "DO $$ BEGIN "
        "IF EXISTS (SELECT 1 FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = 'document_chunks' "
        "AND column_name = 'embedding_vector' AND udt_name <> 'vector') THEN "
        f"ALTER TABLE document_chunks ALTER COLUMN embedding_vector TYPE vector({VECTOR_DIM}) USING NULL; "
        "END IF; END $$"
    )

    # The statement is kept on one source line: the migration guard parses
    # these files to prove every model column has a migration, and a
    # multi-line string concatenation defeats that check.
    op.execute(f"ALTER TABLE document_chunks ADD COLUMN IF NOT EXISTS embedding_vector vector({VECTOR_DIM})")

    with op.get_context().autocommit_block():
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {HNSW_INDEX} "
            "ON document_chunks USING hnsw (embedding_vector vector_cosine_ops)"
        )
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {GIN_INDEX} "
            "ON document_chunks USING gin (to_tsvector('simple', content))"
        )


def downgrade() -> None:
    from app.config import settings

    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {GIN_INDEX}")
        if settings.embeddings_enabled:
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {HNSW_INDEX}")
    op.execute("ALTER TABLE document_chunks DROP COLUMN IF EXISTS embedding_vector")
    # The extension is left installed: other databases may share it, and
    # dropping it would break any object that depends on the type.

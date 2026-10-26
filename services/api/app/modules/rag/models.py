from datetime import datetime, timezone

from pgvector import Vector as VectorValue
from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, Boolean, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import TypeDecorator, UserDefinedType

from ...config import settings
from ...database import Base
from ...db_indexes import register_postgres_index_ddl
from .embeddings import CANONICAL_DIMENSIONS


class _EmbeddingText(UserDefinedType):
    """Renders exactly ``TEXT`` on every dialect.

    Generic ``Text()`` adapts to ``VARCHAR`` under the PostgreSQL dialect,
    while the migration creates ``TEXT``. The two are equivalent in
    PostgreSQL, but the models are the schema source of truth, so the
    rebuild should emit the same DDL the migration does.
    """

    cache_ok = True

    def get_col_spec(self, **kw) -> str:
        return "TEXT"


class EmbeddingVector(TypeDecorator):
    """Physical type of ``document_chunks.embedding_vector``.

    Mirrors the migration's two branches: ``VECTOR(1024)`` when embeddings are
    enabled, a ``TEXT`` placeholder when they are off (development/test, or a
    host without pgvector). Without this, a models-only rebuild would require
    pgvector even in the supported embeddings-off configuration.
    """

    impl = Text
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if self._native_vector(dialect):
            return dialect.type_descriptor(Vector(CANONICAL_DIMENSIONS))
        return _EmbeddingText()

    @staticmethod
    def _native_vector(dialect) -> bool:
        return dialect.name == "postgresql" and settings.embeddings_enabled

    def process_bind_param(self, value, dialect):
        """Serialize a vector for the TEXT fallback.

        The Vector impl does this itself, but a plain Text column would hand
        the driver a Python list, which SQLite rejects. Writing the same text
        form the vector type uses keeps the stored value readable if the
        deployment later enables embeddings.
        """
        if value is None or self._native_vector(dialect):
            return value
        if isinstance(value, str):
            return value
        return VectorValue._to_db(value)

    def process_result_value(self, value, dialect):
        if value is None or self._native_vector(dialect):
            return value
        return VectorValue._from_db(value)


class Databank(Base):
    __tablename__ = "databanks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    accent_color: Mapped[str | None] = mapped_column(String(7), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    databank_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("databanks.id"), index=True
    )
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    filename: Mapped[str] = mapped_column(String(500))
    source_type: Mapped[str] = mapped_column(
        Enum("upload", "scrape", name="document_source_type")
    )
    source_url: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    file_type: Mapped[str] = mapped_column(
        Enum("pdf", "docx", "txt", "md", "csv", "xlsx", "sql", name="document_file_type")
    )
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(
        Enum("pending", "processing", "completed", "failed", name="document_status"),
        default="pending",
    )
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    content_hash: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("documents.id"), index=True
    )
    databank_id: Mapped[str] = mapped_column(String(36), index=True)
    content: Mapped[str] = mapped_column(Text)
    # Legacy JSON copy of the vector. The searchable representation is
    # `embedding_vector` below; this column is kept so a rollback to the
    # pre-pgvector search path still finds the vectors it wrote.
    embedding: Mapped[str | None] = mapped_column(Text, nullable=True)
    # pgvector column. One dimension for every provider, so a chunk written
    # by one model is still comparable with a query built by another width.
    embedding_vector: Mapped[list[float] | None] = mapped_column(
        EmbeddingVector(), nullable=True
    )
    # Tag of the model that produced the vector (provider + model name).
    # Chunks with a different tag are excluded from vector search.
    embedding_model: Mapped[str] = mapped_column(String(100), default="unknown")
    seq: Mapped[int] = mapped_column(Integer, default=0)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class EmbeddingProviderConfig(Base):
    """Admin-managed embedding provider, configured apart from the chat ones.

    The embedding backend has its own key, model and base URL because the two
    are bought and rotated separately, and because vectors from different
    models are not comparable: the model recorded here decides which stored
    chunks the vector search is allowed to score.

    Exactly one row is active at a time. A provider with no active row falls
    back to the text-generation keys (see ``rag.embeddings``), so an
    installation that never configured embeddings keeps working.
    """

    __tablename__ = "embedding_provider_configs"

    provider: Mapped[str] = mapped_column(String(32), primary_key=True)
    model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Fernet-encrypted, exactly like the chat provider keys.
    key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    base_url: Mapped[str | None] = mapped_column(String(200), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    active: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class DataSource(Base):
    """A live database connection (PostgreSQL / MySQL) attached to a databank.

    Credentials are Fernet-encrypted at rest. The password never leaves the
    server except inside an encrypted column — list endpoints omit it.
    """

    __tablename__ = "databank_sources"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    databank_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("databanks.id"), index=True
    )
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(255))
    db_type: Mapped[str] = mapped_column(
        Enum("postgres", "mysql", name="datasource_db_type"), default="postgres"
    )
    host: Mapped[str] = mapped_column(String(255), default="localhost")
    port: Mapped[int] = mapped_column(Integer, default=5432)
    database: Mapped[str] = mapped_column(String(255))
    username: Mapped[str] = mapped_column(String(255))
    password_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class ScrapeJob(Base):
    __tablename__ = "scrape_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    # Postgres does not index a foreign key automatically. Without this,
    # deleting a databank (or listing its jobs) scans the whole table.
    databank_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("databanks.id"), index=True
    )
    user_id: Mapped[str] = mapped_column(String(36))
    # Link to the unified jobs table. NULL for rows created before migration.
    job_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    url: Mapped[str] = mapped_column(String(2000))
    crawl_mode: Mapped[str] = mapped_column(
        Enum("single", "full", name="scrape_crawl_mode"), default="single"
    )
    status: Mapped[str] = mapped_column(
        Enum("pending", "running", "completed", "failed", name="scrape_status"),
        default="pending",
    )
    max_pages: Mapped[int] = mapped_column(Integer, default=50)
    pages_found: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class IngestJob(Base):
    __tablename__ = "ingest_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), index=True)
    # Indexed: both are FK columns, and a databank/document delete would
    # otherwise scan every ingest job. Postgres indexes only the PK.
    databank_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("databanks.id"), index=True
    )
    # Link to the unified jobs table. NULL for rows created before migration.
    job_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    document_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("documents.id"), nullable=True, index=True
    )
    job_type: Mapped[str] = mapped_column(
        Enum("upload", "scrape", "reembed", "reindex", name="ingest_job_type")
    )
    status: Mapped[str] = mapped_column(
        Enum(
            "queued", "parsing", "chunking", "embedding", "indexing", "completed", "failed",
            name="ingest_status",
        ),
        default="queued",
    )
    progress: Mapped[int] = mapped_column(Integer, default=0)
    stage: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


# The keyword index is PostgreSQL-only (expression GIN); the HNSW vector
# index additionally requires pgvector, so it is only created when embeddings
# are enabled. SQLite skips both.
register_postgres_index_ddl(
    DocumentChunk.__table__,
    lambda: [
        "CREATE INDEX IF NOT EXISTS ix_document_chunks_content_gin "
        "ON document_chunks USING gin (to_tsvector('simple', content))",
        *(
            [
                "CREATE INDEX IF NOT EXISTS "
                "ix_document_chunks_embedding_vector_hnsw "
                "ON document_chunks USING hnsw "
                "(embedding_vector vector_cosine_ops)"
            ]
            if settings.embeddings_enabled
            else []
        ),
    ],
    names=[
        "ix_document_chunks_content_gin",
        "ix_document_chunks_embedding_vector_hnsw",
    ],
)

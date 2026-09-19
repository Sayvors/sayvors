from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from ...database import Base


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
    embedding: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding_model: Mapped[str] = mapped_column(String(100), default="bge-m3")
    seq: Mapped[int] = mapped_column(Integer, default=0)
    token_count: Mapped[int] = mapped_column(Integer, default=0)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
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
    databank_id: Mapped[str] = mapped_column(String(36), ForeignKey("databanks.id"))
    user_id: Mapped[str] = mapped_column(String(36))
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
    databank_id: Mapped[str] = mapped_column(String(36), ForeignKey("databanks.id"))
    document_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("documents.id"), nullable=True
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

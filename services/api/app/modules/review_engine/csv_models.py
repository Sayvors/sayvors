"""CSV upload + row storage ORM models."""
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ...database import Base
from ...db_indexes import register_postgres_index_ddl


class CSVUpload(Base):
    """One uploaded CSV.

    ``row_count`` and ``created_at`` are nullable in the migrated table (the
    original migration omitted NOT NULL). The Python defaults still populate
    them on every ORM insert.
    """

    __tablename__ = "csv_uploads"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    column_names: Mapped[list | None] = mapped_column(JSON, nullable=True)
    row_count: Mapped[int | None] = mapped_column(Integer, default=0, nullable=True)
    purpose: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=True,
    )
    rows = relationship("CSVRow", back_populates="upload", cascade="all, delete-orphan")


class CSVRow(Base):
    """One data row of an upload.

    ``upload_id`` and ``created_at`` are nullable in the migrated table; the
    service always sets both, so the ORM path is unaffected.
    """

    __tablename__ = "csv_rows"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    upload_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("csv_uploads.id", ondelete="CASCADE"),
        index=True,
        nullable=True,
    )
    row_index: Mapped[int] = mapped_column(Integer)
    # JSONB on PostgreSQL: csv_service uses the `@>` containment operator and
    # jsonb_each_text(), which do not exist for plain JSON. SQLite keeps JSON.
    data: Mapped[dict | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=True
    )
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=True,
    )
    upload = relationship("CSVUpload", back_populates="rows")


# GIN over the row payload for containment searches. PostgreSQL-only; SQLite
# skips it and the test paths never issue a JSONB query.
register_postgres_index_ddl(
    CSVRow.__table__,
    [
        "CREATE INDEX IF NOT EXISTS idx_csv_rows_data "
        "ON csv_rows USING gin (data jsonb_path_ops)"
    ],
    names=["idx_csv_rows_data"],
)

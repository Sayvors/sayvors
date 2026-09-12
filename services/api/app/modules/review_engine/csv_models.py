"""CSV upload + row storage ORM models."""
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ...database import Base


class CSVUpload(Base):
    __tablename__ = "csv_uploads"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(String(36), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    column_names: Mapped[list | None] = mapped_column(JSON, nullable=True)
    row_count: Mapped[int] = mapped_column(Integer, default=0)
    purpose: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    rows = relationship("CSVRow", back_populates="upload", cascade="all, delete-orphan")


class CSVRow(Base):
    __tablename__ = "csv_rows"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    upload_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("csv_uploads.id", ondelete="CASCADE"), index=True
    )
    row_index: Mapped[int] = mapped_column(Integer)
    data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    upload = relationship("CSVUpload", back_populates="rows")

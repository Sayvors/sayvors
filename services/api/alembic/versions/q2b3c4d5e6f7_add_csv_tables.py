"""add csv_uploads and csv_rows tables

Revision ID: q2b3c4d5e6f7
Revises: p1a2b3c4d5e6
Create Date: 2026-09-12
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = "q2b3c4d5e6f7"
down_revision = "p1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "csv_uploads",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("column_names", sa.JSON(), nullable=True),
        sa.Column("row_count", sa.Integer(), server_default="0"),
        sa.Column("purpose", sa.String(32), nullable=True, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "csv_rows",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("upload_id", sa.String(36), sa.ForeignKey("csv_uploads.id", ondelete="CASCADE"), index=True),
        sa.Column("row_index", sa.Integer(), nullable=False),
        sa.Column("data", JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # GIN index on data for fast JSONB searches
    op.execute("CREATE INDEX IF NOT EXISTS idx_csv_rows_data ON csv_rows USING gin (data jsonb_path_ops)")


def downgrade() -> None:
    op.drop_table("csv_rows")
    op.drop_table("csv_uploads")

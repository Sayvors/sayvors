"""review_intelligence_reports table

Revision ID: i9j0k1l2m3n4
Revises: h8i9j0k1l2m3
Create Date: 2026-09-09 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "i9j0k1l2m3n4"
down_revision: Union[str, None] = "h8i9j0k1l2m3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "review_intelligence_reports",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("channel_id", sa.String(length=36), nullable=False, server_default=""),
        sa.Column("days", sa.Integer(), nullable=False, server_default="90"),
        sa.Column("source", sa.String(length=16), nullable=False, server_default="fallback"),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("themes", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("opportunities", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("strengths", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("actions", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("stats", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("rag_used", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("rag_chunks", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rag_bank", sa.String(length=36), nullable=True),
        sa.Column("fallback_reason", sa.Text(), nullable=True),
        sa.Column("review_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "channel_id", "days", name="uq_intel_report_scope"),
    )
    op.create_index(
        "ix_intel_reports_user_id",
        "review_intelligence_reports",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_intel_reports_user_id", table_name="review_intelligence_reports")
    op.drop_table("review_intelligence_reports")

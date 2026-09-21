"""search_keyword_stats table for Grow search-keyword trends

Revision ID: t6u7v8w9x0y1
Revises: s4t5u6v7w8x9
Create Date: 2026-09-21
"""
import sqlalchemy as sa

from alembic import op

revision = "t6u7v8w9x0y1"
down_revision = "s4t5u6v7w8x9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "search_keyword_stats",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False, index=True),
        sa.Column("channel_id", sa.String(36),
                  sa.ForeignKey("channels.id", ondelete="CASCADE"),
                  nullable=False, index=True),
        sa.Column("keyword", sa.String(255), nullable=False, index=True),
        sa.Column("date", sa.Date(), nullable=False, index=True),
        sa.Column("impressions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.UniqueConstraint("channel_id", "keyword", "date",
                            name="uq_keyword_channel_day"),
    )


def downgrade() -> None:
    op.drop_table("search_keyword_stats")

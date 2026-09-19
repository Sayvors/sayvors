"""location_posts table

Revision ID: l2m3n4o5p6q7
Revises: k1l2m3n4o5p6
Create Date: 2026-09-09 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "l2m3n4o5p6q7"
down_revision: Union[str, None] = "k1l2m3n4o5p6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Plain sa.Enum (checkfirst) instead of raw CREATE TYPE: it queries the
    # catalog first, so partial/replayed runs can never collide.
    op.create_table(
        "location_posts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("listing_id", sa.String(length=64), nullable=False),
        sa.Column("location_name", sa.String(length=255), nullable=True),
        sa.Column("business_name", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("title", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("post_type", sa.Enum("update", "event", "offer", name="post_type"), nullable=False, server_default="update"),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("tags", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("keywords", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("image_urls", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("cta_type", sa.String(length=32), nullable=True),
        sa.Column("cta_url", sa.String(length=1000), nullable=True),
        sa.Column("status", sa.Enum("draft", "scheduled", "published", "failed", "archived", name="post_status"), nullable=False, server_default="draft"),
        sa.Column("scheduled_on", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("localith_response", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_location_posts_user_id", "location_posts", ["user_id"])
    op.create_index("ix_location_posts_listing_id", "location_posts", ["listing_id"])
    op.create_index("ix_location_posts_status", "location_posts", ["status"])


def downgrade() -> None:
    op.drop_index("ix_location_posts_status", table_name="location_posts")
    op.drop_index("ix_location_posts_listing_id", table_name="location_posts")
    op.drop_index("ix_location_posts_user_id", table_name="location_posts")
    op.drop_table("location_posts")
    op.execute("DROP TYPE post_status")
    op.execute("DROP TYPE post_type")

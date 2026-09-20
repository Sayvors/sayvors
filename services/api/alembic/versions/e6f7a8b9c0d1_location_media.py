"""location_media table: scheduled photos that go live on Google.

Photos publish inside Google posts (the only photo path Localith offers);
videos are stored as library rows. Same robustness contract as posts:
per-item locks, retry-then-park, scheduled local deletion.

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-09-20 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e6f7a8b9c0d1"
down_revision: Union[str, None] = "d5e6f7a8b9c0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "location_media",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False),
        sa.Column("listing_id", sa.String(64), index=True, nullable=False),
        sa.Column("image_url", sa.Text(), nullable=False),
        sa.Column("type", sa.Enum("PHOTO", "VIDEO", name="media_type"), nullable=False, server_default="PHOTO"),
        sa.Column("category", sa.String(32), nullable=False, server_default="EXTERIOR"),
        sa.Column("caption", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.Enum("draft", "scheduled", "published", "failed", name="media_status"), nullable=False, server_default="draft", index=True),
        sa.Column("scheduled_on", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delete_at", sa.DateTime(timezone=True), nullable=True, index=True),
        sa.Column("google_post_id", sa.String(128), nullable=True),
        sa.Column("localith_response", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_profile", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_cover", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_media_due", "location_media", ["status", "scheduled_on"])


def downgrade() -> None:
    op.drop_index("ix_media_due", table_name="location_media")
    op.drop_table("location_media")
    op.execute("DROP TYPE IF EXISTS media_status")
    op.execute("DROP TYPE IF EXISTS media_type")

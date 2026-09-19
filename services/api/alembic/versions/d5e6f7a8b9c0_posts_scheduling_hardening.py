"""posts scheduling hardening: delete_at, end_date, retry state.

- delete_at: scheduled local deletion (Google follows its own lifecycle).
- end_date: event/offer end forwarded at publish time — the one Google-side
  removal lever that exists (Google takes ended posts down itself).
- google_post_id: provider post id when returned (reserved for future
  remote deletion: Localith delete or per-tenant native Google).
- attempts / next_retry_at: retry-then-park for failed publishes.
- ix_posts_due: covering index for the worker's hot due-scan.

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-09-19 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d5e6f7a8b9c0"
down_revision: Union[str, None] = "c4d5e6f7a8b9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("location_posts", sa.Column("delete_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("location_posts", sa.Column("end_date", sa.DateTime(timezone=True), nullable=True))
    op.add_column("location_posts", sa.Column("google_post_id", sa.String(128), nullable=True))
    op.add_column(
        "location_posts",
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("location_posts", sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_location_posts_delete_at", "location_posts", ["delete_at"])
    op.create_index("ix_posts_due", "location_posts", ["status", "scheduled_on"])


def downgrade() -> None:
    op.drop_index("ix_posts_due", table_name="location_posts")
    op.drop_index("ix_location_posts_delete_at", table_name="location_posts")
    op.drop_column("location_posts", "next_retry_at")
    op.drop_column("location_posts", "attempts")
    op.drop_column("location_posts", "google_post_id")
    op.drop_column("location_posts", "end_date")
    op.drop_column("location_posts", "delete_at")

"""Review photos and removal tracking on review_insights.

Revision ID: a7b8c9d0e1f2
Revises: e5f6a7b8c9d0
Create Date: 2026-09-26

media        — photos the reviewer attached to a Google review, as
               [{url, kind, label, source_url}]. `url` is OUR copy served
               from /media-files: Google's `reviewMediaItems[].thumbnailUrl`
               is a FIFE link that expires within hours, so storing the URL
               would rot. `source_url` is kept only to notice a changed photo.
last_seen_at — last sync that returned this review.
removed_at   — set when a COMPLETE sync stopped returning it, i.e. Google no
               longer serves the review. Soft: rows and replies are kept, and
               the flag clears itself if the review reappears.

All nullable/defaulted, so existing rows are unaffected.
"""
import sqlalchemy as sa

from alembic import op

revision = "a7b8c9d0e1f2"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "review_insights",
        sa.Column("media", sa.JSON(), nullable=True),
    )
    op.add_column(
        "review_insights",
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "review_insights",
        sa.Column("removed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_review_insights_removed_at",
        "review_insights",
        ["removed_at"],
    )
    # Backfill: everything currently stored was, by definition, returned by a
    # sync, so treat it as seen and not removed.
    op.execute("UPDATE review_insights SET last_seen_at = NOW() WHERE last_seen_at IS NULL")
    op.execute("UPDATE review_insights SET media = '[]'::json WHERE media IS NULL")


def downgrade() -> None:
    op.drop_index("ix_review_insights_removed_at", table_name="review_insights")
    op.drop_column("review_insights", "removed_at")
    op.drop_column("review_insights", "last_seen_at")
    op.drop_column("review_insights", "media")

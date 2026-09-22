"""Merchant-dismissed drafts stay dismissed (review_insights.draft_dismissed).

Revision ID: x0y1z2a3b4c5
Revises: w9x0y1z2a3b4
Create Date: 2026-09-21

Rejecting a draft sets status=rejected — but both reply pipelines only
treat pending/posted/approved as "handled", so the next poll/sync drafted
again and dismissed drafts kept coming back. The marker makes rejection
sticky: sync/worker skip dismissed reviews until the reviewer edits the
review (new content re-arms drafting) or the merchant regenerates manually.
"""
import sqlalchemy as sa

from alembic import op

revision = "x0y1z2a3b4c5"
down_revision = "w9x0y1z2a3b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "review_insights",
        sa.Column("draft_dismissed", sa.Boolean(), nullable=False,
                  server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("review_insights", "draft_dismissed")

"""Add review_insights.missed_syncs (missed it in a7b8c9d0e1f2).

Revision ID: d0e1f2a3b4c5
Revises: b8c9d0e1f2a3
Create Date: 2026-09-26

`missed_syncs` was added to the a7b8c9d0e1f2 migration file AFTER that revision
had already been applied to the database. Alembic does not re-run an applied
revision, so the column was never created while the ORM model has expected it
since. The removal sweep then wrote it on every flush and the statement failed
against a column that did not exist.

This is a separate revision on purpose: editing an already-applied migration
is what caused the drift, so the fix is additive and forward-only.

Removal sweep semantics, now that the column actually exists:
  * incremented each complete sync that does NOT return the review
  * reset to 0 on every sighting (and on any prior verdict being cleared)
  * a review is only marked removed once it has been missed
    MISSES_BEFORE_REMOVAL (2) consecutive times
  * reviews the merchant flagged by hand (skipped) are never swept
"""
import sqlalchemy as sa

from alembic import op

revision = "d0e1f2a3b4c5"
down_revision = "b8c9d0e1f2a3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "review_insights",
        sa.Column(
            "missed_syncs", sa.Integer(), nullable=False, server_default="0"
        ),
    )


def downgrade() -> None:
    op.drop_column("review_insights", "missed_syncs")

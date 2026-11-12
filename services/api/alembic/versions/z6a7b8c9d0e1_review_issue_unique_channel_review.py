"""Unique review issue per (channel, review).

Revision ID: z6a7b8c9d0e1
Revises: z5a6b7c8d9e0
Create Date: 2026-11-12

Two worker replicas both poll every channel and both run the classification
pipeline for the same review before either commits its ``review_issues`` row.
The read-then-insert check in ``_handle_fetched_review`` cannot prevent that
race, so duplicate issues (and duplicate LLM spend) accumulated. This
migration de-duplicates the existing rows and adds a unique index so the
database is the backstop: a losing replica's insert raises IntegrityError,
which the pipeline treats as "already handled" and skips.

Idempotent: the dedupe runs only when duplicates exist, and the index uses
``IF NOT EXISTS``.
"""

from __future__ import annotations

from alembic import op

revision: str = "z6a7b8c9d0e1"
down_revision: str | None = "z5a6b7c8d9e0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Collapse any pre-existing duplicates, keeping the earliest row per
    #    (channel_id, review_id). "Earliest" is by created_at then id so the
    #    choice is deterministic and stable across re-runs.
    op.execute(
        """
        DELETE FROM review_issues
        WHERE id IN (
            SELECT id FROM (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY channel_id, review_id
                           ORDER BY created_at, id
                       ) AS rn
                FROM review_issues
            ) ranked
            WHERE ranked.rn > 1
        )
        """
    )

    # 2. Unique backstop. IF NOT EXISTS keeps a partial deploy re-runnable.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_review_issues_channel_review "
        "ON review_issues (channel_id, review_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_review_issues_channel_review")
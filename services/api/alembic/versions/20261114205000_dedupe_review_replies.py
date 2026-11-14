"""dedupe review_replies before the partial unique index

Revision ID: 20261114205000
Revises: 20261114190000
Create Date: 2026-11-14

The 20261114200000 migration adds a partial unique index on
``review_replies (channel_id, review_id) WHERE status <> 'rejected'``.
Existing deployments can already contain duplicate non-rejected rows —
leftovers of the long-pass double-processing race (M-2) — so creating the
index fails with UniqueViolationError (observed on staging).

This migration runs first and collapses every duplicate group to one row:

  * keep the best row per (channel_id, review_id): posted > pending_approval
    > approved > failed, then newest created_at, then id;
  * rewrite the rest to ``status='rejected'`` (the tombstone the partial
    index excludes), clearing their error text.

Idempotent: after the first run there are no duplicate non-rejected groups,
so a re-run updates nothing.

``review_issues`` already had its unique index (``uq_review_issues_channel_review``)
and needs no backfill.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "20261114205000"
down_revision: Union[str, None] = "20261114190000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        WITH ranked AS (
            SELECT id,
                   row_number() OVER (
                       PARTITION BY channel_id, review_id
                       ORDER BY CASE status
                                  WHEN 'posted' THEN 0
                                  WHEN 'pending_approval' THEN 1
                                  WHEN 'approved' THEN 2
                                  ELSE 3
                                END,
                                created_at DESC,
                                id
                   ) AS rn
            FROM review_replies
            WHERE status <> 'rejected'
        )
        UPDATE review_replies r
        SET status = 'rejected',
            error = NULL
        FROM ranked k
        WHERE r.id = k.id
          AND k.rn > 1
        """
    )


def downgrade() -> None:
    # Not reversible: the original duplicate payloads are already collapsed;
    # restoring them would re-create the violation the index prevents.
    pass

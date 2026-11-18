"""Composite index for the review-replies list page.

The endpoint filters by channel_id + status and sorts by created_at DESC.
With only a single-column channel_id index, every page load sorts the whole
history of a busy listing. The added index matches the filter's leading
column and its sort order, keeping the query flat as replies accumulate.

Revision ID: 20261118140000
Revises: 20261118130000
Create Date: 2026-11-18
"""
from typing import Sequence, Union

from alembic import op

revision: str = "20261118140000"
down_revision: Union[str, None] = "20261118130000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_review_replies_channel_created "
        "ON review_replies (channel_id, created_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_review_replies_channel_created")

"""partial unique index on review_replies (channel_id, review_id)

Prevents duplicate draft / posted / failed reply rows when two worker
replicas process the same Google Reviews channel concurrently during a
long poll pass (passes longer than the 120s per-channel claim lock can
let a second worker claim the channel and double-process reviews).

Only non-rejected rows are unique: a rejected row is a tombstone for a
draft the merchant dismissed, so a later regenerate must be allowed to
insert a fresh row for the same (channel, review).
"""
from typing import Sequence, Union

from alembic import op

revision: str = "20261114200000"
down_revision: Union[str, None] = "20261114205000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_review_replies_channel_review
        ON review_replies (channel_id, review_id)
        WHERE status <> 'rejected'
        """
    )


def downgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS uq_review_replies_channel_review"
    )

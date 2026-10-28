"""Add archived_at to channel_threads (inbox archive chat).

Revision ID: d1e2f3a4b5c6
Revises: m20261027000000
Create Date: 2026-10-27

Soft-archive for inbox threads: a NULL archived_at means the thread is
active; a timestamp hides it from the default inbox view while preserving
the row and its messages. Distinct from deletion, which removes everything.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, None] = "m20261027000000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE channel_threads ADD COLUMN IF NOT EXISTS "
        "archived_at TIMESTAMPTZ"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_channel_threads_archived_at "
        "ON channel_threads (archived_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_channel_threads_archived_at")
    op.execute("ALTER TABLE channel_threads DROP COLUMN IF EXISTS archived_at")

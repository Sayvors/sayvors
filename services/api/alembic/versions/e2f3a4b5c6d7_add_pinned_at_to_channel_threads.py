"""Add pinned_at to channel_threads (server-side pin).

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-10-27

Server-persisted pin: a NULL pinned_at means not pinned; a timestamp pins
the thread (sorts to top of the inbox list). Replaces the client-only
localStorage pin so it follows the tenant across devices.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "e2f3a4b5c6d7"
down_revision: Union[str, None] = "d1e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE channel_threads ADD COLUMN IF NOT EXISTS "
        "pinned_at TIMESTAMPTZ"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_channel_threads_pinned_at "
        "ON channel_threads (pinned_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_channel_threads_pinned_at")
    op.execute("ALTER TABLE channel_threads DROP COLUMN IF EXISTS pinned_at")

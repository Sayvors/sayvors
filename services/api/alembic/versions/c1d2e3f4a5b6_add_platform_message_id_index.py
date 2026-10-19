"""add index on channel_messages.platform_message_id

Every inbound webhook event dedupes with SELECT ... WHERE platform_message_id = :wamid,
which is an O(N) full-table scan on the largest table. A (partial) unique index
makes it O(log N) and prevents twin rows from racing workers.

Revision ID: c1d2e3f4a5b6
Revises: b1c2d3e4f5a6
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'c1d2e3f4a5b6'
down_revision: Union[str, None] = 'b1c2d3e4f5a6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_channel_messages_platform_message_id "
        "ON channel_messages (platform_message_id) "
        "WHERE platform_message_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_channel_messages_platform_message_id")
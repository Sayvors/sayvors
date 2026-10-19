"""add composite index for inbox thread GROUP BY

The inbox GROUP BY on (contact_phone_hash, channel_id) + ORDER BY max(created_at)
was a full table scan. A composite index on (channel_id, contact_phone_hash,
created_at) makes it an index-only scan.

Revision ID: d2e3f4a5b6c7
Revises: c1d2e3f4a5b6
"""
from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'd2e3f4a5b6c7'
down_revision: Union[str, None] = 'c1d2e3f4a5b6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_channel_messages_inbox "
        "ON channel_messages (channel_id, contact_phone_hash, created_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_channel_messages_inbox")
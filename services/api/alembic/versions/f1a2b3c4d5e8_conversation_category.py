"""add category and priority to channel_messages

Inbound conversations are auto-categorised on arrival (Google reviews with
low ratings become complaints, etc.) and the tenant can override the
category manually. The inbox filters and sorts by these columns.

Revision ID: f1a2b3c4d5e8
Revises: e7f8a9b0c1d2
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'f1a2b3c4d5e8'
down_revision: Union[str, None] = 'e7f8a9b0c1d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE channel_messages "
        "ADD COLUMN IF NOT EXISTS category varchar(32)"
    )
    op.execute(
        "ALTER TABLE channel_messages "
        "ADD COLUMN IF NOT EXISTS priority varchar(16)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_channel_messages_category "
        "ON channel_messages (category)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_channel_messages_priority "
        "ON channel_messages (priority)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_channel_messages_priority")
    op.execute("DROP INDEX IF EXISTS ix_channel_messages_category")
    op.execute("ALTER TABLE channel_messages DROP COLUMN IF EXISTS priority")
    op.execute("ALTER TABLE channel_messages DROP COLUMN IF EXISTS category")
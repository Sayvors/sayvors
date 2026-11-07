"""Add Meta delivery timestamps to outbound messages.

The inbox already mirrored Meta's latest status onto ``channel_messages.status``
but threw away *when* each transition happened. That makes a delivery audit
impossible: "delivered" could have arrived at any time, or never. These
columns keep the webhook timestamps so the admin reconciliation can report
first-delivery latency and prove a status came from Meta rather than from our
own send response.

Revision ID: c3e4f5a6b7d8
Revises: b2d3f4a5c6e7
Create Date: 2026-11-07
"""
from typing import Sequence, Union

from alembic import op

revision: str = "c3e4f5a6b7d8"
down_revision: Union[str, None] = "b2d3f4a5c6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE channel_messages ADD COLUMN IF NOT EXISTS delivered_at TIMESTAMPTZ"
    )
    op.execute(
        "ALTER TABLE channel_messages ADD COLUMN IF NOT EXISTS read_at TIMESTAMPTZ"
    )
    op.execute(
        "ALTER TABLE channel_messages ADD COLUMN IF NOT EXISTS failed_at TIMESTAMPTZ"
    )
    # Delivery reconciliation groups outbound rows by (channel, status) inside
    # a date window. The existing channel_created index cannot serve the
    # status grouping; this partial index keeps the admin query an index scan
    # without indexing the (larger) inbound half of the table.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_channel_messages_outbound_status "
        "ON channel_messages (channel_id, status, created_at) "
        "WHERE direction = 'outbound'"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_channel_messages_outbound_status")
    op.execute("ALTER TABLE channel_messages DROP COLUMN IF EXISTS failed_at")
    op.execute("ALTER TABLE channel_messages DROP COLUMN IF EXISTS read_at")
    op.execute("ALTER TABLE channel_messages DROP COLUMN IF EXISTS delivered_at")

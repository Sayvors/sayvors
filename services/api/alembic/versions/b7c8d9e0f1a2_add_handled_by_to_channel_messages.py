"""Add handled_by column to channel_messages.

Revision ID: b7c8d9e0f1a2
Revises: l7m8n9o0p1q2
Create Date: 2026-10-24

Tracks who authored an outbound message (human vs AI) so analytics can
split response performance. Old rows stay "unknown" — no backfill, honest.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b7c8d9e0f1a2"
down_revision: Union[str, None] = "l7m8n9o0p1q2"
branch_labels: Union[Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    handled_by_enum = sa.Enum(
        "human", "ai", "unknown",
        name="message_handled_by",
        create_type=False,
    )
    handled_by_enum.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "channel_messages",
        sa.Column(
            "handled_by",
            handled_by_enum,
            nullable=False,
            server_default="unknown",
        ),
    )
    op.create_index(
        "ix_channel_messages_handled_by",
        "channel_messages",
        ["handled_by"],
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_channel_messages_handled_by", table_name="channel_messages", if_exists=True)
    op.drop_column("channel_messages", "handled_by")

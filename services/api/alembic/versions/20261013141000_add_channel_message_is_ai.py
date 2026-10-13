"""Add channel_messages.is_ai.

Revision ID: 20261013141000
Revises: 20261013140000
Create Date: 2026-10-13

lead_escalation counts consecutive "AI replied, customer wrote again" cycles.
Deciding that from message text would misclassify a human whose reply reads
like the AI's, so the consumer flags the outbound rows it writes itself.

Defaults to false, which is correct for every historical row: none of them
were written by the current AI path, and treating them as human-authored
means no lead starts life with a phantom miss count.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261013141000"
down_revision: Union[str, Sequence[str], None] = "20261013140000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "channel_messages",
        sa.Column("is_ai", sa.Boolean(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("channel_messages", "is_ai")
"""Add lease and processing columns to event_outbox for meta events worker.

Revision ID: 20261012095937
Revises: d8e0f2a4c6b8
Create Date: 2026-10-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261012095937"
down_revision: Union[str, None] = "d8e0f2a4c6b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add lease and processing columns to event_outbox
    op.add_column(
        "event_outbox",
        sa.Column(
            "worker_id",
            sa.String(length=128),
            nullable=True,
            index=True,
        ),
    )
    op.add_column(
        "event_outbox",
        sa.Column(
            "claimed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "event_outbox",
        sa.Column(
            "claimed_until",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "event_outbox",
        sa.Column(
            "processing_started_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    # Add index for claiming queries
    op.create_index(
        "ix_event_outbox_claim",
        "event_outbox",
        ["status", "next_retry_at", "claimed_until"],
    )
    # Add index for lease expiration queries
    op.create_index(
        "ix_event_outbox_claimed_until",
        "event_outbox",
        ["claimed_until"],
    )


def downgrade() -> None:
    # Remove indexes
    op.drop_index("ix_event_outbox_claim", table_name="event_outbox")
    op.drop_index("ix_event_outbox_claimed_until", table_name="event_outbox")
    # Remove columns
    op.drop_column("event_outbox", "processing_started_at")
    op.drop_column("event_outbox", "claimed_until")
    op.drop_column("event_outbox", "claimed_at")
    op.drop_column("event_outbox", "worker_id")
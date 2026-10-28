"""Add human_handled_out column to channel_daily_metrics.

Revision ID: a2b3c4d5e6f7a8b9
Revises: f0a1b2c3d4e5f6a7
Create Date: 2026-10-24

Tracks outbound messages authored by a human (handled_by="human") separately
from AI-authored ones, so the analytics UI can show an honest split instead
of lumping "unknown/legacy" rows into "human".
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a2b3c4d5e6f7a8b9"
down_revision: Union[str, None] = "f0a1b2c3d4e5f6a7"
branch_labels: Union[Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "channel_daily_metrics",
        sa.Column("human_handled_out", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("channel_daily_metrics", "human_handled_out")

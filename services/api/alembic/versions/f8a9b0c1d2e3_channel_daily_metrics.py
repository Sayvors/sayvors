"""Messaging daily rollups: channel_daily_metrics.

Revision ID: f8a9b0c1d2e3
Revises: d8e0f2a4c6b8
Create Date: 2026-10-10

The messaging analog of location_daily_metrics. The rollup worker
(`analytics/messaging_rollup.py`) writes one row per channel per day —
message volume, conversation response health (median/p90 FRT, response
rate), unanswered snapshots, comment reply coverage. Analytics endpoints
read these stored rows only; nothing derives messaging metrics from
channel_messages at request time.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f8a9b0c1d2e3"
down_revision: Union[str, None] = "d8e0f2a4c6b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "channel_daily_metrics",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("channel_id", sa.String(36), sa.ForeignKey("channels.id"), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("messages_in", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("messages_out", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("conversations_in", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("conversations_replied", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("median_first_response_seconds", sa.Integer(), nullable=True),
        sa.Column("p90_first_response_seconds", sa.Integer(), nullable=True),
        sa.Column("frt_samples", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("unanswered_open", sa.Integer(), nullable=True),
        sa.Column("oldest_unanswered_seconds", sa.Integer(), nullable=True),
        sa.Column("comments_in", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("comments_replied", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ai_handled_out", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("contacts_new", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("followers_count", sa.Integer(), nullable=True),
        sa.Column("posts_count", sa.Integer(), nullable=True),
        sa.Column("by_hour_in", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column(
            "computed_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("channel_id", "date", name="uq_channel_daily_channel_date"),
    )
    op.create_index("ix_channel_daily_metrics_user_id", "channel_daily_metrics", ["user_id"])
    op.create_index("ix_channel_daily_metrics_channel_id", "channel_daily_metrics", ["channel_id"])
    op.create_index("ix_channel_daily_metrics_date", "channel_daily_metrics", ["date"])


def downgrade() -> None:
    op.drop_table("channel_daily_metrics")

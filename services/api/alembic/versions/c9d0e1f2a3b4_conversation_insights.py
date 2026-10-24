"""Conversation insights table for "what customers ask" mining.

Revision ID: c9d0e1f2a3b4
Revises: b7c8d9e0f1a2
Create Date: 2026-10-24

Stores LLM-mined conversation insights per tenant per rolling window.
Written ONLY by the insights worker; endpoints read stored JSON only.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c9d0e1f2a3b4"
down_revision: Union[str, None] = "b7c8d9e0f1a2"
branch_labels: Union[Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "conversation_insights",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False, index=True),
        sa.Column("window_start", sa.Date(), nullable=False),
        sa.Column("window_end", sa.Date(), nullable=False),
        sa.Column("insights", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("message_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_conversation_insights_tenant_window",
        "conversation_insights",
        ["tenant_id", "window_start", "window_end"],
        unique=True,
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_conversation_insights_tenant_window", table_name="conversation_insights", if_exists=True)
    op.drop_table("conversation_insights")

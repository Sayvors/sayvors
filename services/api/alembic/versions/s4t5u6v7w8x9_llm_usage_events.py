"""llm usage events metering table

Revision ID: s4t5u6v7w8x9
Revises: r3s4t5u6v7w8
Create Date: 2026-09-12
"""
import sqlalchemy as sa

from alembic import op

revision = "s4t5u6v7w8x9"
down_revision = "r3s4t5u6v7w8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llm_usage_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=True, index=True),
        sa.Column("provider", sa.String(32), nullable=False, index=True),
        sa.Column("model_id", sa.String(100), nullable=True, index=True),
        sa.Column("api_model", sa.String(200), nullable=False),
        sa.Column("purpose", sa.String(60), nullable=True, index=True),
        sa.Column("channel_id", sa.String(36), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(16), nullable=False, server_default="ok"),
        sa.Column("error", sa.String(300), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now(), index=True),
    )


def downgrade() -> None:
    op.drop_table("llm_usage_events")

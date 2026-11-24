"""create cover_monitors

Revision ID: 20261123150000
Revises: 20261122130000
Create Date: 2026-11-23
"""
from alembic import op
import sqlalchemy as sa

revision = "20261123150000"
down_revision = "20261122130000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "cover_monitors",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel_id", sa.String(255), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("account_id", sa.String(255), nullable=False, server_default=""),
        sa.Column("location_id", sa.String(255), nullable=False, server_default=""),
        sa.Column("expected_name", sa.String(512), nullable=False, server_default=""),
        sa.Column("expected_image_url", sa.Text, nullable=False, server_default=""),
        sa.Column("actual_name", sa.String(512), nullable=True),
        sa.Column("actual_image_url", sa.Text, nullable=True),
        sa.Column("status", sa.String(12), nullable=False, server_default="ok"),
        sa.Column("drift_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("error", sa.String(500), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_cover_monitors_tenant_id", "cover_monitors", ["tenant_id"])
    op.create_index("ix_cover_monitors_channel_id", "cover_monitors", ["channel_id"])
    op.create_index("ix_cover_monitors_status", "cover_monitors", ["status"])
    op.create_index(
        "uq_cover_monitor_tenant_channel",
        "cover_monitors",
        ["tenant_id", "channel_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_cover_monitor_tenant_channel", table_name="cover_monitors")
    op.drop_index("ix_cover_monitors_status", table_name="cover_monitors")
    op.drop_index("ix_cover_monitors_channel_id", table_name="cover_monitors")
    op.drop_index("ix_cover_monitors_tenant_id", table_name="cover_monitors")
    op.drop_table("cover_monitors")

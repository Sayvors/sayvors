"""add cover monitor auto-replace

Revision ID: 20261123173000
Revises: 20261123150000
Create Date: 2026-11-23
"""
from alembic import op
import sqlalchemy as sa

revision = "20261123173000"
down_revision = "20261123150000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "cover_monitors",
        sa.Column("auto_replace", sa.Boolean(), nullable=False, server_default="true"),
    )
    op.add_column(
        "cover_monitors",
        sa.Column("auto_replace_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "cover_monitors",
        sa.Column("last_auto_replace_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("cover_monitors", "last_auto_replace_at")
    op.drop_column("cover_monitors", "auto_replace_count")
    op.drop_column("cover_monitors", "auto_replace")

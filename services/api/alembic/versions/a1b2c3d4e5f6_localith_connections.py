"""localith_connections table

Revision ID: a1b2c3d4e5f6
Revises: e4f5a6b7c8d9
Create Date: 2026-09-07 15:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f6a7b8c9d0e1"
down_revision: Union[str, None] = "f5a6b7c8d9e0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "localith_connections",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("listing_id", sa.String(length=64), nullable=False),
        sa.Column("listing_name", sa.String(length=255), nullable=False),
        sa.Column("listing_google_id", sa.String(length=128), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_localith_user"),
    )
    op.create_index(
        "ix_localith_connections_user_id",
        "localith_connections",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_localith_connections_user_id", table_name="localith_connections")
    op.drop_table("localith_connections")

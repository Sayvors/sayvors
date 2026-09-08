"""verification state and merchant services per Google channel

Revision ID: b2c3d4e5f6a7
Revises: f6a7b8c9d0e1
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "channel_verifications",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("channel_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("method", sa.String(length=30), nullable=True),
        sa.Column("contact_target", sa.String(length=255), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("channel_id"),
    )
    op.create_index("ix_channel_verifications_channel_id", "channel_verifications", ["channel_id"])

    op.create_table(
        "channel_services",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("channel_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("category", sa.String(length=120), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("is_offered", sa.Boolean(), nullable=False),
        sa.Column("source", sa.String(length=30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_channel_services_channel_id", "channel_services", ["channel_id"])


def downgrade() -> None:
    op.drop_index("ix_channel_services_channel_id", table_name="channel_services")
    op.drop_table("channel_services")
    op.drop_index("ix_channel_verifications_channel_id", table_name="channel_verifications")
    op.drop_table("channel_verifications")

"""location_profiles table

Revision ID: k1l2m3n4o5p6
Revises: j0k1l2m3n4o5
Create Date: 2026-09-09 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "k1l2m3n4o5p6"
down_revision: Union[str, None] = "j0k1l2m3n4o5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "location_profiles",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("listing_id", sa.String(length=64), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("categories", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("hours", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("service_area", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("attributes", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "listing_id", name="uq_location_profile_listing"),
    )
    op.create_index(
        "ix_location_profiles_user_id",
        "location_profiles",
        ["user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_location_profiles_user_id", table_name="location_profiles")
    op.drop_table("location_profiles")

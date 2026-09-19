"""multi-location Localith connections (one row per branch).

Replaces the single-listing-per-user constraint with a per-(user, listing)
constraint so every branch a tenant connects is stored, synced, and kept
— pages filter per branch instead of assuming one location.

Revision ID: v7w8x9y0z1a2
Revises: u6v7w8x9y0z1
Create Date: 2026-09-16 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op


revision: str = "v7w8x9y0z1a2"
down_revision: Union[str, None] = "u6v7w8x9y0z1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("uq_localith_user", "localith_connections", type_="unique")
    op.create_unique_constraint(
        "uq_localith_user_listing", "localith_connections", ["user_id", "listing_id"]
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_localith_user_listing", "localith_connections", type_="unique"
    )
    op.create_unique_constraint(
        "uq_localith_user", "localith_connections", ["user_id"]
    )

"""localith profile + metrics snapshot columns

Revision ID: g7h8i9j0k1l2
Revises: f6a7b8c9d0e1
Create Date: 2026-09-09 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "g7h8i9j0k1l2"
down_revision: Union[str, None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("localith_connections", sa.Column("address", sa.String(length=500), nullable=True))
    op.add_column("localith_connections", sa.Column("phone_number", sa.String(length=64), nullable=True))
    op.add_column("localith_connections", sa.Column("website_url", sa.String(length=500), nullable=True))
    op.add_column("localith_connections", sa.Column("maps_url", sa.String(length=500), nullable=True))
    op.add_column("localith_connections", sa.Column("store_code", sa.String(length=128), nullable=True))
    op.add_column("localith_connections", sa.Column("is_verified", sa.Boolean(), nullable=True))
    op.add_column("localith_connections", sa.Column("is_disabled", sa.Boolean(), nullable=True))
    op.add_column("localith_connections", sa.Column("is_suspended", sa.Boolean(), nullable=True))
    op.add_column("localith_connections", sa.Column("total_reviews", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("localith_connections", sa.Column("average_rating", sa.Float(), nullable=False, server_default="0"))
    op.add_column("localith_connections", sa.Column("last_review_on", sa.DateTime(timezone=True), nullable=True))
    op.add_column("localith_connections", sa.Column("last_reply_on", sa.DateTime(timezone=True), nullable=True))
    op.add_column("localith_connections", sa.Column("raw_listing_json", sa.JSON(), nullable=True))
    op.add_column("localith_connections", sa.Column("profile_synced_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("localith_connections", sa.Column("raw_metrics_json", sa.JSON(), nullable=True))
    op.add_column("localith_connections", sa.Column("raw_item_metrics_json", sa.JSON(), nullable=True))
    op.add_column("localith_connections", sa.Column("metrics_start", sa.Date(), nullable=True))
    op.add_column("localith_connections", sa.Column("metrics_end", sa.Date(), nullable=True))
    op.add_column("localith_connections", sa.Column("metrics_synced_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    for col in (
        "metrics_synced_at", "metrics_end", "metrics_start",
        "raw_item_metrics_json", "raw_metrics_json", "profile_synced_at",
        "raw_listing_json", "last_reply_on", "last_review_on",
        "average_rating", "total_reviews", "is_suspended", "is_disabled",
        "is_verified", "store_code", "maps_url", "website_url",
        "phone_number", "address",
    ):
        op.drop_column("localith_connections", col)

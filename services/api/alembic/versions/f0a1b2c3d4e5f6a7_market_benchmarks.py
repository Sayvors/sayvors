"""Market benchmarks table for cross-tenant response-time comparison.

Revision ID: f0a1b2c3d4e5f6a7
Revises: c9d0e1f2a3b4
Create Date: 2026-10-24

Stores aggregate (median/p25/p75) response metrics across all tenants,
computed by a cross-tenant worker. Endpoints read stored rows only — no
cross-tenant queries on the request path.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f0a1b2c3d4e5f6a7"
down_revision: Union[str, None] = "c9d0e1f2a3b4"
branch_labels: Union[Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "market_benchmarks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("date", sa.Date(), nullable=False, index=True),
        sa.Column("scope_market", sa.String(64), nullable=False, server_default="global"),
        sa.Column("scope_network", sa.String(32), nullable=False, server_default="all"),
        sa.Column("metric", sa.String(64), nullable=False),
        sa.Column("median", sa.Float(), nullable=True),
        sa.Column("p25", sa.Float(), nullable=True),
        sa.Column("p75", sa.Float(), nullable=True),
        sa.Column("business_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_market_benchmarks_date_scope",
        "market_benchmarks",
        ["date", "scope_market", "scope_network", "metric"],
        unique=True,
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_market_benchmarks_date_scope", table_name="market_benchmarks", if_exists=True)
    op.drop_table("market_benchmarks")

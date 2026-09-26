"""review_intelligence_reports: scorecard columns + per-interval cache slot

Revision ID: d4e5f6a7b8c9
Revises: cf45046e3531
Create Date: 2026-09-26
"""
from alembic import op
import sqlalchemy as sa

revision = "d4e5f6a7b8c9"
down_revision = "cf45046e3531"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "review_intelligence_reports",
        sa.Column("dimensions", sa.JSON(), nullable=True),
    )
    op.add_column(
        "review_intelligence_reports",
        sa.Column("competitive", sa.JSON(), nullable=True),
    )
    # Cache identity moves from `days` to `scope_key` so an explicit month
    # range ("2026-09-01..2026-09-30") can own a slot of its own instead of
    # colliding with every other custom range on days=0.
    op.add_column(
        "review_intelligence_reports",
        sa.Column("scope_key", sa.String(length=40), nullable=True),
    )
    op.execute(
        "UPDATE review_intelligence_reports SET scope_key = days::text "
        "WHERE scope_key IS NULL"
    )
    op.drop_constraint(
        "uq_intel_report_scope",
        "review_intelligence_reports",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_intel_report_scope",
        "review_intelligence_reports",
        ["user_id", "channel_id", "scope_key"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_intel_report_scope",
        "review_intelligence_reports",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_intel_report_scope",
        "review_intelligence_reports",
        ["user_id", "channel_id", "days"],
    )
    op.drop_column("review_intelligence_reports", "scope_key")
    op.drop_column("review_intelligence_reports", "competitive")
    op.drop_column("review_intelligence_reports", "dimensions")

"""review_insights.skipped flag (merchant-dismissed reviews).

The sync and analytics code reads/writes insight.skipped, but no migration
ever created the column — fresh databases fail every Localith sync (and the
?status=skipped insights query) with UndefinedColumnError. Existing rows
backfill as not-skipped.

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
Create Date: 2026-09-19 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b3c4d5e6f7a8"
down_revision: Union[str, None] = "a2b3c4d5e6f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "review_insights",
        sa.Column("skipped", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("review_insights", "skipped")

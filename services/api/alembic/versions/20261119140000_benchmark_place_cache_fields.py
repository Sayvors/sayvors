"""Address and category types on the bench row, so a cached comparison column is complete.

Revision ID: 20261119140000
Revises: 20261119120000
Create Date: 2026-11-19

The comparison page shows a business's address and services. Until now those
lived only in the live Places response, so a cached (stored) column could not
render them. They become part of the cache the scraper and a live read refresh.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261119140000"
down_revision: Union[str, None] = "20261119120000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "benchmark_places",
        sa.Column("address", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "benchmark_places",
        sa.Column("types", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("benchmark_places", "types")
    op.drop_column("benchmark_places", "address")

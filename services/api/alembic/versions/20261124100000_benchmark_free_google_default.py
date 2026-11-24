"""default benchmark source to the free Google endpoints

Revision ID: 20261124100000
Revises: 20261123173000
Create Date: 2026-11-24
"""
from alembic import op

revision = "20261124100000"
down_revision = "20261123173000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # gosom is retired; google_places rows without a key were idling the
    # collector. Outscraper stays untouched because it is an explicit paid
    # choice. Idempotent so a partially-applied deploy can safely re-run.
    op.execute(
        "ALTER TABLE benchmark_config ALTER COLUMN source SET DEFAULT 'boq'"
    )
    op.execute(
        "UPDATE benchmark_config SET source = 'boq' "
        "WHERE source IN ('gosom', 'google_places')"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE benchmark_config SET source = 'google_places' WHERE source = 'boq'"
    )
    op.execute(
        "ALTER TABLE benchmark_config ALTER COLUMN source SET DEFAULT 'google_places'"
    )

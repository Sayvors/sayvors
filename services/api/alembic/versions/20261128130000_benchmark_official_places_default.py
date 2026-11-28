"""Default benchmark source to official Google Places.

Revision ID: 20261128130000
Revises: 20261128120000
"""
from alembic import op

revision = "20261128130000"
down_revision = "20261128120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Places is authoritative for facts when a key is configured. The runtime
    # provider falls back to BOQ when the key is absent or the call fails, so
    # this default does not idle the collector on deployments with no key.
    op.execute(
        "ALTER TABLE benchmark_config ALTER COLUMN source SET DEFAULT 'google_places'"
    )
    op.execute(
        "UPDATE benchmark_config SET source = 'google_places' WHERE source = 'boq'"
    )


def downgrade() -> None:
    op.execute("UPDATE benchmark_config SET source = 'boq' WHERE source = 'google_places'")
    op.execute("ALTER TABLE benchmark_config ALTER COLUMN source SET DEFAULT 'boq'")

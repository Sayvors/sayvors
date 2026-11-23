"""benchmark gosom source column and place maps_url / reviews_per_score

Revision ID: 20261122120000
Revises: 20261122110000
Create Date: 2026-11-22
"""
from alembic import op
import sqlalchemy as sa

revision = "20261122120000"
down_revision = "20261122110000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE benchmark_config "
        "ADD COLUMN IF NOT EXISTS source VARCHAR(20) NOT NULL DEFAULT 'google_places'"
    )
    op.execute(
        "ALTER TABLE benchmark_places ADD COLUMN IF NOT EXISTS maps_url VARCHAR(1024)"
    )
    op.execute(
        "ALTER TABLE benchmark_places ADD COLUMN IF NOT EXISTS reviews_per_score JSON"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE benchmark_places DROP COLUMN IF EXISTS reviews_per_score")
    op.execute("ALTER TABLE benchmark_places DROP COLUMN IF EXISTS maps_url")
    op.execute("ALTER TABLE benchmark_config DROP COLUMN IF EXISTS source")
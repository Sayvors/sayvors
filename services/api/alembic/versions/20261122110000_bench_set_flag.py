"""benchmark set membership flag on saved places

Revision ID: 20261122110000
Revises: 20261122101000
Create Date: 2026-11-22
"""
from alembic import op
import sqlalchemy as sa

revision = "20261122110000"
down_revision = "20261122101000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE benchmark_places "
        "ADD COLUMN IF NOT EXISTS in_bench_set BOOLEAN NOT NULL DEFAULT FALSE"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_benchmark_places_bench_set "
        "ON benchmark_places (tenant_id) WHERE in_bench_set"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_benchmark_places_bench_set")
    op.execute("ALTER TABLE benchmark_places DROP COLUMN IF EXISTS in_bench_set")

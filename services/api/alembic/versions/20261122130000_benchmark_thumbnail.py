"""Add thumbnail (Google place photo) to saved benchmark places

Revision ID: 20261122130000
Revises: 20261122120000
Create Date: 2026-11-23
"""
from alembic import op

revision = "20261122130000"
down_revision = "20261122120000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE benchmark_places "
        "ADD COLUMN IF NOT EXISTS thumbnail VARCHAR(1024)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE benchmark_places DROP COLUMN IF EXISTS thumbnail")

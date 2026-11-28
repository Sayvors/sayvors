"""Add bounded full-history benchmark review settings.

Revision ID: 20261128140000
Revises: 20261128130000
"""
from alembic import op

revision = "20261128140000"
down_revision = "20261128130000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE benchmark_config ADD COLUMN IF NOT EXISTS "
        "review_history_mode VARCHAR(16) NOT NULL DEFAULT 'recent'"
    )
    op.execute(
        "ALTER TABLE benchmark_config ADD COLUMN IF NOT EXISTS "
        "max_reviews_per_place INTEGER NOT NULL DEFAULT 2000"
    )
    op.execute(
        "ALTER TABLE benchmark_config ADD COLUMN IF NOT EXISTS "
        "full_history_batch INTEGER NOT NULL DEFAULT 1"
    )
    op.execute(
        "UPDATE benchmark_config SET review_history_mode = 'recent' "
        "WHERE review_history_mode NOT IN ('recent', 'full') OR review_history_mode IS NULL"
    )
    op.execute(
        "UPDATE benchmark_config SET max_reviews_per_place = LEAST(GREATEST(max_reviews_per_place, 10), 20000) "
        "WHERE max_reviews_per_place IS NULL OR max_reviews_per_place < 10 OR max_reviews_per_place > 20000"
    )
    op.execute(
        "UPDATE benchmark_config SET full_history_batch = LEAST(GREATEST(full_history_batch, 1), 10) "
        "WHERE full_history_batch IS NULL OR full_history_batch < 1 OR full_history_batch > 10"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE benchmark_config DROP COLUMN IF EXISTS full_history_batch")
    op.execute("ALTER TABLE benchmark_config DROP COLUMN IF EXISTS max_reviews_per_place")
    op.execute("ALTER TABLE benchmark_config DROP COLUMN IF EXISTS review_history_mode")

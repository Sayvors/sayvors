"""Benchmark history: scraper retention, scrape-error column and lookup index.

Revision ID: 20261119120000
Revises: 20261118170000
Create Date: 2026-11-19

`retention_days` used to be 2 because snapshots were only a cache. They are now
the history the comparison page reads for its 30/90/365-day views, so the
default becomes two years and any config row still on the old cache value is
lifted with it. The scraper records its last failure per place so an outage is
visible instead of silent.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "20261119120000"
down_revision: Union[str, None] = "20261118170000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

DEFAULT_RETENTION_DAYS = 730


def upgrade() -> None:
    op.execute(
        f"""
        ALTER TABLE benchmark_config
        ALTER COLUMN retention_days SET DEFAULT {DEFAULT_RETENTION_DAYS}
        """
    )
    # Rows created before history existed still carry the 2-day cache TTL,
    # which would delete every snapshot the moment the scraper runs.
    op.execute(
        f"""
        UPDATE benchmark_config
        SET retention_days = {DEFAULT_RETENTION_DAYS}
        WHERE retention_days < 30
        """
    )
    op.execute(
        """
        ALTER TABLE benchmark_places
        ADD COLUMN IF NOT EXISTS last_scrape_error VARCHAR(300)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_benchmark_snapshots_tenant_place_fetched
        ON benchmark_snapshots (tenant_id, place_id, fetched_at)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_benchmark_snapshots_tenant_place_fetched")
    op.execute("ALTER TABLE benchmark_places DROP COLUMN IF EXISTS last_scrape_error")
    op.execute("ALTER TABLE benchmark_config ALTER COLUMN retention_days SET DEFAULT 2")

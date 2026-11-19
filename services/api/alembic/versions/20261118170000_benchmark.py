"""Benchmark bench, snapshots and config.

Revision ID: 20261118170000
Revises: 20261118160000
Create Date: 2026-11-19
"""
from typing import Sequence, Union

from alembic import op

revision: str = "20261118170000"
down_revision: Union[str, None] = "20261118160000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS benchmark_config (
            id VARCHAR(16) PRIMARY KEY,
            place_cache_enabled BOOLEAN NOT NULL DEFAULT true,
            retention_days INTEGER NOT NULL DEFAULT 2,
            refresh_hours INTEGER NOT NULL DEFAULT 24,
            max_saved_places INTEGER NOT NULL DEFAULT 50,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "INSERT INTO benchmark_config (id) VALUES ('default') ON CONFLICT (id) DO NOTHING"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS benchmark_places (
            id VARCHAR(36) PRIMARY KEY,
            tenant_id VARCHAR(36) NOT NULL,
            place_id VARCHAR(255) NOT NULL,
            label VARCHAR(120),
            notes TEXT,
            in_heatmap BOOLEAN NOT NULL DEFAULT true,
            name VARCHAR(255),
            rating FLOAT,
            review_count INTEGER,
            latitude FLOAT,
            longitude FLOAT,
            reviews JSONB,
            photos JSONB,
            fetched_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_benchmark_tenant_place UNIQUE (tenant_id, place_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_benchmark_places_tenant_created "
        "ON benchmark_places (tenant_id, created_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_benchmark_places_tenant_id "
        "ON benchmark_places (tenant_id)"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS benchmark_snapshots (
            id VARCHAR(36) PRIMARY KEY,
            place_id VARCHAR(36) NOT NULL,
            tenant_id VARCHAR(36) NOT NULL,
            rating FLOAT,
            review_count INTEGER,
            reviews JSONB,
            fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_benchmark_snapshot_place_time UNIQUE (place_id, fetched_at)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_benchmark_snapshots_tenant_fetched "
        "ON benchmark_snapshots (tenant_id, fetched_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_benchmark_snapshots_place_id "
        "ON benchmark_snapshots (place_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_benchmark_snapshots_place_id")
    op.execute("DROP INDEX IF EXISTS ix_benchmark_snapshots_tenant_fetched")
    op.execute("DROP TABLE IF EXISTS benchmark_snapshots")
    op.execute("DROP INDEX IF EXISTS ix_benchmark_places_tenant_id")
    op.execute("DROP INDEX IF EXISTS ix_benchmark_places_tenant_created")
    op.execute("DROP TABLE IF EXISTS benchmark_places")
    op.execute("DROP TABLE IF EXISTS benchmark_config")

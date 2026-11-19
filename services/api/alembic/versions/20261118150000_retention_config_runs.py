"""Admin-configurable retention policy and archive run audit.

Revision ID: 20261118150000
Revises: 20261118140000
Create Date: 2026-11-18
"""
from typing import Sequence, Union

from alembic import op

revision: str = "20261118150000"
down_revision: Union[str, None] = "20261118140000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS retention_config (
            id VARCHAR(16) PRIMARY KEY,
            review_log_days INTEGER NOT NULL DEFAULT 90,
            connect_event_days INTEGER NOT NULL DEFAULT 30,
            backup_lead_days INTEGER NOT NULL DEFAULT 2,
            archive_enabled BOOLEAN NOT NULL DEFAULT false,
            review_log_archived_through TIMESTAMPTZ,
            connect_event_archived_through TIMESTAMPTZ,
            last_run_at TIMESTAMPTZ,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "INSERT INTO retention_config (id) VALUES ('default') "
        "ON CONFLICT (id) DO NOTHING"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS retention_runs (
            id VARCHAR(36) PRIMARY KEY,
            kind VARCHAR(32) NOT NULL,
            action VARCHAR(16) NOT NULL,
            s3_key VARCHAR(500),
            rows INTEGER NOT NULL DEFAULT 0,
            size_bytes BIGINT,
            status VARCHAR(16) NOT NULL DEFAULT 'running',
            trigger_type VARCHAR(16) NOT NULL DEFAULT 'manual',
            error TEXT,
            started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            finished_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_retention_runs_started "
        "ON retention_runs (started_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_retention_runs_kind "
        "ON retention_runs (kind, started_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_retention_runs_kind")
    op.execute("DROP INDEX IF EXISTS ix_retention_runs_started")
    op.execute("DROP TABLE IF EXISTS retention_runs")
    op.execute("DROP TABLE IF EXISTS retention_config")

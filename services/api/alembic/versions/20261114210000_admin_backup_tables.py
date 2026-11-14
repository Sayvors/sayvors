"""admin backup config + run history tables

Revision ID: 20261114210000
Revises: 20261114200000
Create Date: 2026-11-14

Gives the admin console a durable view of backups:

- ``admin_backup_config`` — single-row scheduler config (interval hours,
  enabled, S3 bucket/region, last/next run). The scheduler worker and the
  admin API read and update this row.
- ``admin_backup_runs`` — one row per backup attempt (manual or scheduled)
  with status, S3 key, size, timestamps and error text, so the admin page
  can show history and the last result even when S3 is unreachable.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "20261114210000"
down_revision: Union[str, None] = "20261114200000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS admin_backup_config (
            id VARCHAR(16) PRIMARY KEY,
            enabled BOOLEAN NOT NULL DEFAULT FALSE,
            interval_hours INTEGER NOT NULL DEFAULT 24,
            bucket VARCHAR(255),
            region VARCHAR(32) NOT NULL DEFAULT 'eu-north-1',
            last_run_at TIMESTAMPTZ,
            next_run_at TIMESTAMPTZ,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT admin_backup_config_interval_positive CHECK (interval_hours >= 1)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS admin_backup_runs (
            id VARCHAR(36) PRIMARY KEY,
            backup_key VARCHAR(500),
            status VARCHAR(16) NOT NULL DEFAULT 'running',
            trigger_type VARCHAR(16) NOT NULL DEFAULT 'manual',
            size_bytes BIGINT,
            error TEXT,
            started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            finished_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_admin_backup_runs_started "
        "ON admin_backup_runs (started_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_admin_backup_runs_key "
        "ON admin_backup_runs (backup_key)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS admin_backup_runs")
    op.execute("DROP TABLE IF EXISTS admin_backup_config")

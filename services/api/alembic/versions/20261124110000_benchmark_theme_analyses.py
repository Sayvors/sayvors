"""Add durable benchmark review-theme analyses and job enum value.

Revision ID: 20261124110000
Revises: 20261124100000
Create Date: 2026-11-24
"""
from alembic import op

revision = "20261124110000"
down_revision = "20261124100000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # PostgreSQL enum additions cannot run inside a transaction. IF NOT EXISTS
    # makes a partially applied deploy safe to resume.
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE job_type ADD VALUE IF NOT EXISTS 'benchmark.theme_extract'"
        )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS benchmark_theme_analyses (
            id VARCHAR(36) PRIMARY KEY,
            tenant_id VARCHAR(36) NOT NULL,
            subject_type VARCHAR(8) NOT NULL,
            subject_id VARCHAR(36) NOT NULL,
            sample_hash CHAR(64) NOT NULL,
            sample_json JSON NOT NULL DEFAULT '[]'::json,
            themes JSON NOT NULL DEFAULT '[]'::json,
            status VARCHAR(16) NOT NULL DEFAULT 'pending',
            source VARCHAR(8),
            model VARCHAR(255),
            error TEXT,
            job_id VARCHAR(36),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_benchmark_theme_analysis_subject
                UNIQUE (tenant_id, subject_type, subject_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_benchmark_theme_analyses_tenant_id "
        "ON benchmark_theme_analyses (tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_benchmark_theme_analysis_status_updated "
        "ON benchmark_theme_analyses (status, updated_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_benchmark_theme_analysis_status_updated")
    op.execute("DROP INDEX IF EXISTS ix_benchmark_theme_analyses_tenant_id")
    op.execute("DROP TABLE IF EXISTS benchmark_theme_analyses")
    # PostgreSQL cannot remove one enum value without rewriting dependent rows;
    # the unused value is harmless and matches the existing job-type migrations.

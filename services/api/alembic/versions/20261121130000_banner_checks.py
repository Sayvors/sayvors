"""banner_checks table: queued AI suitability analysis for banner photos.

Revision ID: 20261121130000
Revises: 20261121120000
Create Date: 2026-11-21

Publication of a Promotion waits on this check, so the row is what the
composer polls while the realtime lane runs the analysis. Idempotent DDL:
a staging database that already created the table (out of band) must not
crash the migration chain.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "20261121130000"
down_revision: Union[str, None] = "20261121120000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS banner_checks (
            id VARCHAR(36) PRIMARY KEY,
            tenant_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            status VARCHAR(12) NOT NULL DEFAULT 'queued',
            media_key VARCHAR(500),
            media_url VARCHAR(1024),
            suitable VARCHAR(8),
            confidence INTEGER,
            summary TEXT,
            checks_json TEXT,
            ai_verdict_json TEXT,
            decision_json TEXT,
            error VARCHAR(300),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_banner_checks_tenant ON banner_checks (tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_banner_checks_status ON banner_checks (status)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS banner_checks")

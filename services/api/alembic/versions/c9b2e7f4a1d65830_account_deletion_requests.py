"""account_deletion_requests

Thirty-day owner personal-data deletion flow. The request row is the audit
trail; the workspace business records are retained. Signing in during the
window cancels the request.

Revision ID: c9b2e7f4a1d65830
Revises: f3a6c8e1d4b97520
"""

from typing import Sequence, Union

from alembic import op

revision: str = "c9b2e7f4a1d65830"
down_revision: Union[str, None] = "f3a6c8e1d4b97520"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS account_deletion_requests (
            id VARCHAR(36) PRIMARY KEY,
            tenant_id VARCHAR(36) NOT NULL,
            requested_by VARCHAR(36),
            status VARCHAR(16) NOT NULL DEFAULT 'pending',
            requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            scheduled_for TIMESTAMPTZ NOT NULL,
            cancelled_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            reminder_sent_at TIMESTAMPTZ,
            reason VARCHAR(200),
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_account_deletion_requests_tenant_id "
        "ON account_deletion_requests (tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_account_deletion_tenant_status "
        "ON account_deletion_requests (tenant_id, status)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_account_deletion_due "
        "ON account_deletion_requests (status, scheduled_for)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_account_deletion_due")
    op.execute("DROP INDEX IF EXISTS ix_account_deletion_tenant_status")
    op.execute("DROP INDEX IF EXISTS ix_account_deletion_requests_tenant_id")
    op.execute("DROP TABLE IF EXISTS account_deletion_requests")

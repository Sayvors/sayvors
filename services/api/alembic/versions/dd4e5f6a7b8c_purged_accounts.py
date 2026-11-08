"""Archive for accounts purged without an owner request (unverified signups).

Deleting an unverified account should leave an admin-visible trace: who it was,
when they signed up, when it was removed, and why. This table is platform-level
(no tenant columns) so it survives a tenant purge and can never be exported with
a workspace.

Revision ID: dd4e5f6a7b8c
Revises: cc3d4e5f6a7b
Create Date: 2026-11-08
"""
from typing import Sequence, Union

from alembic import op

revision: str = "dd4e5f6a7b8c"
down_revision: Union[str, None] = "cc3d4e5f6a7b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS purged_accounts (
            id VARCHAR(36) PRIMARY KEY,
            email VARCHAR(320) NOT NULL,
            first_name VARCHAR(120),
            last_name VARCHAR(120),
            reason VARCHAR(32) NOT NULL DEFAULT 'unverified',
            status VARCHAR(16) NOT NULL DEFAULT 'pending',
            error VARCHAR(500),
            signed_up_at TIMESTAMPTZ,
            purged_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_purged_accounts_email "
        "ON purged_accounts (email)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_purged_accounts_purged_at "
        "ON purged_accounts (purged_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_purged_accounts_status "
        "ON purged_accounts (status)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_purged_accounts_status")
    op.execute("DROP INDEX IF EXISTS ix_purged_accounts_purged_at")
    op.execute("DROP INDEX IF EXISTS ix_purged_accounts_email")
    op.execute("DROP TABLE IF EXISTS purged_accounts")

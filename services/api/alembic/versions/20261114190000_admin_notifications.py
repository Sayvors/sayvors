"""admin notifications

Revision ID: 20261114190000
Revises: 20261114180000
Create Date: 2026-11-14

In-app notifications for platform operators (bell). operator_id NULL rows are
broadcast to every admin. Kinds: request, error, finance, system.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20261114190000"
down_revision: Union[str, None] = "20261114180000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS admin_notifications (
            id VARCHAR(36) PRIMARY KEY,
            operator_id VARCHAR(36) REFERENCES platform_operators(id) ON DELETE CASCADE,
            kind VARCHAR(24) NOT NULL DEFAULT 'system',
            severity VARCHAR(12) NOT NULL DEFAULT 'info',
            title VARCHAR(200) NOT NULL,
            body TEXT,
            href VARCHAR(300),
            read_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_admin_notifications_operator_read_created "
        "ON admin_notifications (operator_id, read_at, created_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_admin_notifications_created "
        "ON admin_notifications (created_at)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS admin_notifications")

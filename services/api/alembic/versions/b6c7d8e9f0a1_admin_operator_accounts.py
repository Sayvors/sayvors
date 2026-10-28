"""admin operator accounts + audit log

Replaces the single shared admin password with named operator accounts.
Creates platform_operators and admin_audit_logs tables.

Revision ID: b6c7d8e9f0a1
Revises: d5e6f7a8b9c0d1
Create Date: 2026-10-25
"""
from alembic import op
import sqlalchemy as sa


revision = "b6c7d8e9f0a1"
down_revision = "d5e6f7a8b9c0d1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # platform_operators
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS platform_operators (
            id VARCHAR(36) PRIMARY KEY,
            username VARCHAR(64) NOT NULL UNIQUE,
            password_hash VARCHAR(255) NOT NULL,
            role VARCHAR(32) NOT NULL DEFAULT 'operator',
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            failed_login_count INTEGER NOT NULL DEFAULT 0,
            locked_until TIMESTAMPTZ NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            last_login_at TIMESTAMPTZ NULL
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_platform_operators_username ON platform_operators (username)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_platform_operators_role ON platform_operators (role)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_platform_operators_is_active ON platform_operators (is_active)")

    # admin_audit_logs
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS admin_audit_logs (
            id VARCHAR(36) PRIMARY KEY,
            operator_id VARCHAR(36) NULL REFERENCES platform_operators(id) ON DELETE SET NULL,
            operator_username VARCHAR(64) NULL,
            action VARCHAR(64) NOT NULL,
            method VARCHAR(10) NOT NULL,
            path VARCHAR(256) NOT NULL,
            status_code INTEGER NOT NULL DEFAULT 0,
            ip VARCHAR(64) NULL,
            user_agent VARCHAR(256) NULL,
            detail TEXT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_admin_audit_logs_operator_id ON admin_audit_logs (operator_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_admin_audit_logs_operator_username ON admin_audit_logs (operator_username)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_admin_audit_logs_action ON admin_audit_logs (action)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_admin_audit_logs_created_at ON admin_audit_logs (created_at)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS admin_audit_logs")
    op.execute("DROP TABLE IF EXISTS platform_operators")

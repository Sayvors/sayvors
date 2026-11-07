"""Separate top-ups and sales-assisted plan requests.

Payments are not connected yet, so a tenant cannot buy a message pack or an
Enterprise plan directly. Instead they submit a request; an operator approves
it and the approval applies the change (message/channel allowance or AI
credit), which keeps the same accounting path as an admin grant.

Revision ID: f9a1b2c3d4e5
Revises: c3e4f5a6b7d8
Create Date: 2026-11-07
"""
from typing import Sequence, Union

from alembic import op

revision: str = "f9a1b2c3d4e5"
down_revision: Union[str, None] = "c3e4f5a6b7d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS billing_requests (
            id VARCHAR(36) PRIMARY KEY,
            tenant_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            kind VARCHAR(16) NOT NULL,
            plan_slug VARCHAR(40),
            amount INTEGER,
            note TEXT,
            status VARCHAR(16) NOT NULL DEFAULT 'pending',
            created_by VARCHAR(36),
            reviewed_by VARCHAR(64),
            reviewed_at TIMESTAMPTZ,
            decision_note TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_billing_requests_tenant_created "
        "ON billing_requests (tenant_id, created_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_billing_requests_status_created "
        "ON billing_requests (status, created_at)"
    )
    # Per-tenant allowances bought on top of the plan. NULL = inherit the plan.
    op.execute(
        "ALTER TABLE tenant_subscriptions "
        "ADD COLUMN IF NOT EXISTS message_limit_override INTEGER"
    )
    op.execute(
        "ALTER TABLE tenant_subscriptions "
        "ADD COLUMN IF NOT EXISTS channels_limit_override INTEGER"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE tenant_subscriptions DROP COLUMN IF EXISTS channels_limit_override")
    op.execute("ALTER TABLE tenant_subscriptions DROP COLUMN IF EXISTS message_limit_override")
    op.execute("DROP INDEX IF EXISTS ix_billing_requests_status_created")
    op.execute("DROP INDEX IF EXISTS ix_billing_requests_tenant_created")
    op.execute("DROP TABLE IF EXISTS billing_requests")


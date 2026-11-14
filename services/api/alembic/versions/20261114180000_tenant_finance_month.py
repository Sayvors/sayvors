"""tenant finance monthly snapshots

Revision ID: 20261114180000
Revises: 20261114170000
Create Date: 2026-11-14

Admin financials: one row per tenant per month with the plan price billed,
credits consumed, actual delivered cost (provider + infra from the metering
events), collected amount, payment status, and admin adjustments/notes.
Unique (tenant_id, month) — recompute is an upsert.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20261114180000"
down_revision: Union[str, None] = "20261114170000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS tenant_finance_month (
            id VARCHAR(36) PRIMARY KEY,
            tenant_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            month DATE NOT NULL,
            plan_slug VARCHAR(40),
            plan_name VARCHAR(80),
            plan_price_cents INTEGER NOT NULL DEFAULT 0,
            credits_used_cents INTEGER NOT NULL DEFAULT 0,
            actual_cost_micro BIGINT NOT NULL DEFAULT 0,
            collected_cents INTEGER NOT NULL DEFAULT 0,
            status VARCHAR(16) NOT NULL DEFAULT 'unpaid',
            adjustments JSON NOT NULL DEFAULT '{}',
            note TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_tenant_finance_month_tenant_month "
        "ON tenant_finance_month (tenant_id, month)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_tenant_finance_month "
        "ON tenant_finance_month (month)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS tenant_finance_month")

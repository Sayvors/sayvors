"""plan max_regenerations_day cap + durable daily regeneration counter

Revision ID: 20261114160000
Revises: 20261114150000
Create Date: 2026-11-14

§34 item 4 of the readiness report: cap how many review replies a tenant can
manually regenerate per day. The regenerate endpoint previously had only a
global per-channel rate limit (Redis, 100/60s); this adds a durable per-tenant
daily quota. Counting LLM usage events cannot isolate manual regenerations from
worker auto-replies (same purpose "review_engine.generate"), so a small
counter table keyed by (tenant_id, usage_date) is the source of truth.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20261114160000"
down_revision: Union[str, None] = "20261114150000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE plans ADD COLUMN IF NOT EXISTS max_regenerations_day INTEGER")
    # Seed tier values. Idempotent: only fills rows that have no value yet, so
    # an admin's explicit edit is never overwritten by a re-run.
    op.execute(
        """
        UPDATE plans SET max_regenerations_day = 5
        WHERE slug = 'free-trial' AND max_regenerations_day IS NULL
        """
    )
    op.execute(
        """
        UPDATE plans SET max_regenerations_day = 25
        WHERE slug = 'starter' AND max_regenerations_day IS NULL
        """
    )
    op.execute(
        """
        UPDATE plans SET max_regenerations_day = 100
        WHERE slug = 'pro' AND max_regenerations_day IS NULL
        """
    )
    op.execute(
        """
        UPDATE plans SET max_regenerations_day = 500
        WHERE slug = 'growth' AND max_regenerations_day IS NULL
        """
    )
    # Durable per-tenant daily counter. One row per tenant per day; the
    # unique index is the race boundary (upsert wins, never twins).
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS regeneration_usage (
            id VARCHAR(36) PRIMARY KEY,
            tenant_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            usage_date DATE NOT NULL,
            count INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_regeneration_usage_tenant_date "
        "ON regeneration_usage (tenant_id, usage_date)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS regeneration_usage")
    op.execute("ALTER TABLE plans DROP COLUMN IF EXISTS max_regenerations_day")

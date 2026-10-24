"""Turn billing_events into the durable AI-credit ledger.

The wallet hotfix left Redis as the live counter and ``billing_events`` as a
grants-only audit table. This migration adds the hold/settlement columns the
runtime ledger needs. It does not move any balances: the opening baseline is
written per tenant by ``ensure_ledger_initialized`` or the backfill script,
after the operator has previewed the computed balance.

Idempotent: every column and index is added with IF NOT EXISTS, so re-running
against a database that already has the ledger shape is a no-op.
"""
from alembic import op

revision = "i4j5k6l7m8n9"
down_revision = "h3a4b5c6d7e8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE billing_events "
        "ADD COLUMN IF NOT EXISTS status VARCHAR(16) NOT NULL DEFAULT 'posted'"
    )
    op.execute(
        "ALTER TABLE billing_events "
        "ADD COLUMN IF NOT EXISTS reserved_cents INTEGER NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE billing_events ADD COLUMN IF NOT EXISTS model_id VARCHAR(100)"
    )
    op.execute(
        "ALTER TABLE billing_events "
        "ADD COLUMN IF NOT EXISTS prompt_tokens INTEGER NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE billing_events "
        "ADD COLUMN IF NOT EXISTS completion_tokens INTEGER NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE billing_events ADD COLUMN IF NOT EXISTS idempotency_key VARCHAR(160)"
    )
    op.execute(
        "ALTER TABLE billing_events ADD COLUMN IF NOT EXISTS expires_at TIMESTAMPTZ"
    )
    op.execute(
        "ALTER TABLE billing_events ADD COLUMN IF NOT EXISTS settled_at TIMESTAMPTZ"
    )
    op.execute(
        "ALTER TABLE billing_events "
        "ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT now()"
    )

    # A NULL key means "no idempotency requirement" and must not collide with
    # other rows; a non-NULL key is unique per tenant.
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_billing_events_tenant_idempotency "
        "ON billing_events (tenant_id, idempotency_key) "
        "WHERE idempotency_key IS NOT NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_billing_events_status_expires "
        "ON billing_events (status, expires_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_billing_events_tenant_status "
        "ON billing_events (tenant_id, status)"
    )

    # The usage row is the recovery point if a provider returns but the
    # settle call dies: the reaper can find the hold through ledger_id.
    op.execute(
        "ALTER TABLE llm_usage_events "
        "ADD COLUMN IF NOT EXISTS cost_cents INTEGER NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE llm_usage_events ADD COLUMN IF NOT EXISTS ledger_id VARCHAR(36)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_llm_usage_events_ledger_id "
        "ON llm_usage_events (ledger_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_llm_usage_events_ledger_id")
    op.execute("ALTER TABLE llm_usage_events DROP COLUMN IF EXISTS ledger_id")
    op.execute("ALTER TABLE llm_usage_events DROP COLUMN IF EXISTS cost_cents")

    op.execute("DROP INDEX IF EXISTS ix_billing_events_tenant_status")
    op.execute("DROP INDEX IF EXISTS ix_billing_events_status_expires")
    op.execute("DROP INDEX IF EXISTS uq_billing_events_tenant_idempotency")
    for column in (
        "updated_at",
        "settled_at",
        "expires_at",
        "idempotency_key",
        "completion_tokens",
        "prompt_tokens",
        "model_id",
        "reserved_cents",
        "status",
    ):
        op.execute(f"ALTER TABLE billing_events DROP COLUMN IF EXISTS {column}")

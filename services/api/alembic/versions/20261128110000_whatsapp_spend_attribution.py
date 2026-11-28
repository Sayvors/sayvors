"""Add WhatsApp quota reservations, monthly usage, and Meta spend facts.

Revision ID: 20261128110000
Revises: 20261128100000
"""
from alembic import op

revision = "20261128110000"
down_revision = "20261128100000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS whatsapp_spend_daily (
            id VARCHAR(36) PRIMARY KEY,
            tenant_id VARCHAR(36) NOT NULL,
            waba_id VARCHAR(100) NOT NULL,
            messaging_account_id VARCHAR(100),
            spend_date DATE NOT NULL,
            phone VARCHAR(50),
            country VARCHAR(8),
            pricing_category VARCHAR(50),
            pricing_type VARCHAR(50),
            tier VARCHAR(50),
            attribution_hash VARCHAR(64) NOT NULL,
            volume BIGINT NOT NULL DEFAULT 0,
            cost NUMERIC(20, 6),
            currency VARCHAR(8),
            cost_status VARCHAR(20) NOT NULL,
            funding_mode VARCHAR(40) NOT NULL,
            waba_timezone VARCHAR(64),
            source VARCHAR(30) NOT NULL DEFAULT 'pricing_analytics',
            fetched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_whatsapp_spend_daily_attribution
                UNIQUE (tenant_id, waba_id, spend_date, attribution_hash),
            CONSTRAINT ck_whatsapp_spend_daily_volume CHECK (volume >= 0),
            CONSTRAINT ck_whatsapp_spend_daily_cost CHECK (cost IS NULL OR cost >= 0),
            CONSTRAINT ck_whatsapp_spend_daily_cost_status
                CHECK (cost_status IN ('available', 'unavailable')),
            CONSTRAINT ck_whatsapp_spend_daily_funding_mode
                CHECK (funding_mode IN (
                    'direct_client', 'shared_credit_line', 'platform_liable', 'unknown'
                ))
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS whatsapp_quota_reservations (
            id VARCHAR(36) PRIMARY KEY,
            tenant_id VARCHAR(36) NOT NULL,
            channel VARCHAR(20) NOT NULL DEFAULT 'whatsapp',
            month DATE NOT NULL,
            idempotency_key VARCHAR(160) NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'reserved',
            phone_number_id VARCHAR(100),
            provider_message_id VARCHAR(200),
            failure_classification VARCHAR(40),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            settled_at TIMESTAMPTZ,
            CONSTRAINT uq_whatsapp_quota_reservations_tenant_key
                UNIQUE (tenant_id, idempotency_key),
            CONSTRAINT ck_whatsapp_quota_reservations_status
                CHECK (status IN ('reserved', 'consumed', 'released'))
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS whatsapp_monthly_usage (
            tenant_id VARCHAR(36) NOT NULL,
            month DATE NOT NULL,
            used_count INTEGER NOT NULL DEFAULT 0,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (tenant_id, month),
            CONSTRAINT uq_whatsapp_monthly_usage_tenant_month
                UNIQUE (tenant_id, month),
            CONSTRAINT ck_whatsapp_monthly_usage_used CHECK (used_count >= 0)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS ix_whatsapp_spend_daily_tenant_date ON whatsapp_spend_daily (tenant_id, spend_date)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_whatsapp_spend_daily_waba_date ON whatsapp_spend_daily (waba_id, spend_date)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_whatsapp_spend_daily_funding_date ON whatsapp_spend_daily (funding_mode, spend_date)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_whatsapp_quota_reservations_tenant_month ON whatsapp_quota_reservations (tenant_id, month)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_whatsapp_quota_reservations_provider_message ON whatsapp_quota_reservations (provider_message_id) WHERE provider_message_id IS NOT NULL")
    op.execute("ALTER TABLE channel_messages ADD COLUMN IF NOT EXISTS pricing_billable BOOLEAN")
    op.execute("ALTER TABLE channel_messages ADD COLUMN IF NOT EXISTS pricing_model JSONB")
    op.execute("ALTER TABLE channel_messages ADD COLUMN IF NOT EXISTS pricing_category VARCHAR(50)")
    op.execute("ALTER TABLE channel_messages ADD COLUMN IF NOT EXISTS pricing_type VARCHAR(50)")
    op.execute("ALTER TABLE channel_messages ADD COLUMN IF NOT EXISTS pricing_subtype VARCHAR(50)")
    op.execute("ALTER TABLE channel_messages ADD COLUMN IF NOT EXISTS provider_confirmed_at TIMESTAMPTZ")
    op.execute("ALTER TABLE channel_messages ADD COLUMN IF NOT EXISTS quota_idempotency_key VARCHAR(160)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_channel_messages_quota_idempotency ON channel_messages (quota_idempotency_key)")
    # Existing outbound rows remain authoritative for the current month. The
    # conflict guard makes a re-run harmless after reservation accounting starts.
    op.execute("""
        INSERT INTO whatsapp_monthly_usage (tenant_id, month, used_count, updated_at)
        SELECT c.user_id, date_trunc('month', now())::date, count(*), now()
        FROM channel_messages cm
        JOIN channels c ON c.id = cm.channel_id
        WHERE c.platform = 'whatsapp'
          AND cm.direction = 'outbound'
          AND cm.created_at >= date_trunc('month', now())
        GROUP BY c.user_id
        ON CONFLICT (tenant_id, month) DO NOTHING
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS whatsapp_quota_reservations")
    op.execute("DROP TABLE IF EXISTS whatsapp_monthly_usage")
    op.execute("DROP TABLE IF EXISTS whatsapp_spend_daily")
    op.execute("DROP INDEX IF EXISTS ix_channel_messages_quota_idempotency")
    for column in (
        "pricing_billable", "pricing_model", "pricing_category",
        "pricing_type", "pricing_subtype", "provider_confirmed_at",
        "quota_idempotency_key",
    ):
        op.execute(f"ALTER TABLE channel_messages DROP COLUMN IF EXISTS {column}")

"""Durable email outbox, provider events and suppression list.

Email used to be one synchronous Resend call inside the request. This adds the
tables a worker needs to retry safely, and the suppression list that protects
the sending domain from bounces and complaints.

Revision ID: f3b4c5d6e7a8
Revises: d1f2a3b4c5e6
Create Date: 2026-11-07
"""
from typing import Sequence, Union

from alembic import op

revision: str = "f3b4c5d6e7a8"
down_revision: Union[str, None] = "d1f2a3b4c5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS email_outbox (
            id VARCHAR(36) PRIMARY KEY,
            tenant_id VARCHAR(36),
            to_email VARCHAR(320) NOT NULL,
            subject VARCHAR(500) NOT NULL,
            html TEXT NOT NULL,
            text TEXT,
            kind VARCHAR(32) NOT NULL,
            headers JSONB NOT NULL DEFAULT '{}'::jsonb,
            idempotency_key VARCHAR(160),
            status VARCHAR(16) NOT NULL DEFAULT 'queued',
            attempts INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 6,
            next_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            provider_id VARCHAR(120),
            error TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            sent_at TIMESTAMPTZ
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_email_outbox_status_due ON email_outbox (status, next_attempt_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_email_outbox_tenant_created ON email_outbox (tenant_id, created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_email_outbox_to_email ON email_outbox (to_email)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_email_outbox_provider_id ON email_outbox (provider_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_email_outbox_created_at ON email_outbox (created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_email_outbox_status ON email_outbox (status)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_email_outbox_kind ON email_outbox (kind)")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_email_outbox_idempotency "
        "ON email_outbox (idempotency_key) WHERE idempotency_key IS NOT NULL"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS email_events (
            id VARCHAR(36) PRIMARY KEY,
            outbox_id VARCHAR(36),
            email VARCHAR(320) NOT NULL,
            type VARCHAR(24) NOT NULL,
            provider_event_id VARCHAR(160),
            detail TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_email_events_outbox_id ON email_events (outbox_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_email_events_email ON email_events (email)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_email_events_type ON email_events (type)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_email_events_email_created ON email_events (email, created_at)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_email_events_type_created ON email_events (type, created_at)")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_email_events_provider_event "
        "ON email_events (provider_event_id) WHERE provider_event_id IS NOT NULL"
    )

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS email_suppressions (
            email VARCHAR(320) PRIMARY KEY,
            reason VARCHAR(24) NOT NULL,
            detail TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS email_suppressions")
    op.execute("DROP TABLE IF EXISTS email_events")
    op.execute("DROP TABLE IF EXISTS email_outbox")

"""Newsletter campaigns and the outbox link.

A campaign is composed once, then expanded into `email_outbox` in paced
batches. `campaign_id` lets the admin UI report progress from the real delivery
rows instead of a second counter that can drift.

Revision ID: cc3d4e5f6a7b
Revises: bb2c3d4e5f6a
Create Date: 2026-11-08
"""
from typing import Sequence, Union

from alembic import op

revision: str = "cc3d4e5f6a7b"
down_revision: Union[str, None] = "bb2c3d4e5f6a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS email_campaigns (
            id VARCHAR(36) PRIMARY KEY,
            created_by VARCHAR(64),
            subject VARCHAR(500) NOT NULL,
            html TEXT NOT NULL,
            text TEXT,
            status VARCHAR(16) NOT NULL DEFAULT 'draft',
            total_recipients INTEGER NOT NULL DEFAULT 0,
            expanded_recipients INTEGER NOT NULL DEFAULT 0,
            last_user_id VARCHAR(36),
            max_user_id VARCHAR(36),
            batch_size INTEGER NOT NULL DEFAULT 500,
            interval_seconds INTEGER NOT NULL DEFAULT 60,
            next_expand_at TIMESTAMPTZ,
            error VARCHAR(500),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            started_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            cancelled_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_email_campaigns_status_due "
        "ON email_campaigns (status, next_expand_at)"
    )
    op.execute(
        "ALTER TABLE email_outbox ADD COLUMN IF NOT EXISTS campaign_id VARCHAR(36)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_email_outbox_campaign "
        "ON email_outbox (campaign_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_email_outbox_campaign")
    op.execute("ALTER TABLE email_outbox DROP COLUMN IF EXISTS campaign_id")
    op.execute("DROP INDEX IF EXISTS ix_email_campaigns_status_due")
    op.execute("DROP TABLE IF EXISTS email_campaigns")

"""Review Campaigns: time-boxed review-request asks with plan limits.

Revision ID: 20261118160000
Revises: 20261118150000
Create Date: 2026-11-18
"""
from typing import Sequence, Union

from alembic import op

revision: str = "20261118160000"
down_revision: Union[str, None] = "20261118150000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS review_campaigns (
            id VARCHAR(36) PRIMARY KEY,
            tenant_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name VARCHAR(120) NOT NULL,
            from_date DATE NOT NULL,
            to_date DATE NOT NULL,
            status VARCHAR(16) NOT NULL DEFAULT 'scheduled',
            message_template TEXT,
            channel_id VARCHAR(36) REFERENCES channels(id) ON DELETE SET NULL,
            duplicated_from VARCHAR(36),
            recipient_count INTEGER NOT NULL DEFAULT 0,
            sent_count INTEGER NOT NULL DEFAULT 0,
            clicked_count INTEGER NOT NULL DEFAULT 0,
            reviewed_count INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_review_campaigns_tenant_created "
        "ON review_campaigns (tenant_id, created_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_review_campaigns_tenant_status "
        "ON review_campaigns (tenant_id, status)"
    )
    op.execute(
        "ALTER TABLE review_requests ADD COLUMN IF NOT EXISTS campaign_id VARCHAR(36) "
        "REFERENCES review_campaigns(id) ON DELETE SET NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_review_requests_campaign "
        "ON review_requests (campaign_id)"
    )
    op.execute(
        "ALTER TABLE plans ADD COLUMN IF NOT EXISTS max_campaigns_per_month INTEGER"
    )
    op.execute(
        "ALTER TABLE plans ADD COLUMN IF NOT EXISTS max_campaign_days INTEGER"
    )
    # Defaults only where unset, so an operator's existing values survive.
    # trial: one 7-day ask per week; growth/pro: 14 days a month;
    # enterprise: no monthly cap, windows up to 30 days.
    for slug, monthly, days in (
        ("free-trial", 4, 7),
        ("starter", 2, 7),
        ("pro", 2, 14),
        ("growth", 2, 14),
        ("enterprise", None, 30),
    ):
        op.execute(
            f"UPDATE plans SET max_campaigns_per_month = "
            f"{'NULL' if monthly is None else monthly}, "
            f"max_campaign_days = {days} "
            f"WHERE slug = '{slug}' AND max_campaign_days IS NULL"
        )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_review_requests_campaign")
    op.execute("ALTER TABLE review_requests DROP COLUMN IF EXISTS campaign_id")
    op.execute("DROP INDEX IF EXISTS ix_review_campaigns_tenant_status")
    op.execute("DROP INDEX IF EXISTS ix_review_campaigns_tenant_created")
    op.execute("DROP TABLE IF EXISTS review_campaigns")
    op.execute("ALTER TABLE plans DROP COLUMN IF EXISTS max_campaign_days")
    op.execute("ALTER TABLE plans DROP COLUMN IF EXISTS max_campaigns_per_month")

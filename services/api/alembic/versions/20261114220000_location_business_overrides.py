"""location_business_overrides table

Revision ID: 20261114220000
Revises: 20261114210000
Create Date: 2026-11-14

Merchant-edited business details per Google location (name, categories with
sub/sub-sub, services, regular hours, special hours). The merchant's values
win over Google when the AI builds its facts; ``google_snapshot`` keeps the
official Google values for the side-by-side compare view.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "20261114220000"
down_revision: Union[str, None] = "20261114210000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS location_business_overrides (
            id VARCHAR(36) PRIMARY KEY,
            user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            listing_id VARCHAR(64) NOT NULL,
            name VARCHAR(255),
            categories JSON NOT NULL DEFAULT '{}',
            services JSON NOT NULL DEFAULT '[]',
            hours JSON NOT NULL DEFAULT '{}',
            special_hours JSON NOT NULL DEFAULT '[]',
            google_snapshot JSONB NOT NULL DEFAULT '{}',
            source VARCHAR(16) NOT NULL DEFAULT 'auto',
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            CONSTRAINT uq_location_business_override_listing UNIQUE (user_id, listing_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_location_business_overrides_user "
        "ON location_business_overrides (user_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_location_business_overrides_listing "
        "ON location_business_overrides (listing_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS location_business_overrides")

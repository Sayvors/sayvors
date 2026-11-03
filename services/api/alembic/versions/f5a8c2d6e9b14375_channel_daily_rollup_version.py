"""Add channel_daily_metrics.rollup_version for bounded history heal.

The messaging rollup previously grouped conversations and first-time
contacts by the Fernet `contact_phone` ciphertext. Fernet is non-deterministic,
so every message looked like a new contact and every message was its own
conversation. The worker now groups by `contact_phone_hash`, and this version
column lets it recompute pre-fix rows in bounded slices instead of leaving
frozen wrong counts in the 30/90-day Growth card.

Revision ID: f5a8c2d6e9b14375
Revises: f5a8c2d6e9b14374
"""
from typing import Sequence, Union

from alembic import op

revision: str = "f5a8c2d6e9b14375"
down_revision: Union[str, None] = "f5a8c2d6e9b14374"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE channel_daily_metrics "
        "ADD COLUMN IF NOT EXISTS rollup_version INTEGER NOT NULL DEFAULT 0"
    )


def downgrade() -> None:
    op.drop_column("channel_daily_metrics", "rollup_version")

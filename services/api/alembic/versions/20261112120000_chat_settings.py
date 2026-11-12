"""per-user chat voice knobs (reply temperature, linter rollout flag)

Revision ID: 20261112120000
Revises: m1n2o3p4q5r6
Create Date: 2026-11-12

Phase 4 of the WA voice plan: rollout knobs live in a JSON column (NULL =
safe defaults), the same pattern as lead_settings/notification_settings — a
new knob never needs a migration. Values are clamped by
chat_voice.normalize_chat_settings, never trusted raw.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20261112120000"
down_revision: Union[str, None] = "m1n2o3p4q5r6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS chat_settings JSON"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE users DROP COLUMN IF EXISTS chat_settings"
    )

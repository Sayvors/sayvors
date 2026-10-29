"""auto_reply_configs.databank_grounding

Per-channel switch for customer-facing retrieval. The distilled business
profile was already injected into every reply, but the assistant never
searched the databank for the specific question, so prices and policies were
either guessed or deferred.

Default ON: an empty databank retrieves nothing, so the switch only has an
effect once there is content to ground on.

Revision ID: fbd90ec030b0
Revises: 2cb0d67d62f0
Create Date: 2026-10-29
"""
from alembic import op

revision = "fbd90ec030b0"
down_revision = "2cb0d67d62f0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE auto_reply_configs "
        "ADD COLUMN IF NOT EXISTS databank_grounding boolean "
        "NOT NULL DEFAULT true"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE auto_reply_configs DROP COLUMN IF EXISTS databank_grounding"
    )

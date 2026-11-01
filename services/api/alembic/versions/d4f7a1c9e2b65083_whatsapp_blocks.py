"""whatsapp_blocks

Mirror the provider-side block state on the thread so the inbox can render
"Block" / "Unblock" without a Graph call per thread. WhatsApp owns the actual
block; these columns are a cache of the last successful action.

Revision ID: d4f7a1c9e2b65083
Revises: a7c1e9b4d2f60835
"""

from typing import Sequence, Union

from alembic import op

revision: str = "d4f7a1c9e2b65083"
down_revision: Union[str, None] = "a7c1e9b4d2f60835"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE channel_threads "
        "ADD COLUMN IF NOT EXISTS blocked_at TIMESTAMPTZ"
    )
    op.execute(
        "ALTER TABLE channel_threads "
        "ADD COLUMN IF NOT EXISTS blocked_by VARCHAR(36)"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE channel_threads DROP COLUMN IF EXISTS blocked_by"
    )
    op.execute(
        "ALTER TABLE channel_threads DROP COLUMN IF EXISTS blocked_at"
    )

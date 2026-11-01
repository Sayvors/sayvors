"""message_actions

WA-4 support on stored messages:

* reply_to_message_id — the wamid a contextual reply quotes.
* deleted_at / deleted_by — a local "remove from inbox" marker. Meta's Cloud
  API does not expose edit or delete for sent messages, so this is explicitly
  internal; the row is retained for audit and excluded from AI history.

Revision ID: f6a2d9c4e713805b
Revises: a1f4c8e2d9b7035
"""

from typing import Sequence, Union

from alembic import op

revision: str = "f6a2d9c4e713805b"
down_revision: Union[str, None] = "a1f4c8e2d9b7035"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE channel_messages "
        "ADD COLUMN IF NOT EXISTS reply_to_message_id VARCHAR(200)"
    )
    op.execute(
        "ALTER TABLE channel_messages "
        "ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ"
    )
    op.execute(
        "ALTER TABLE channel_messages "
        "ADD COLUMN IF NOT EXISTS deleted_by VARCHAR(36)"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE channel_messages DROP COLUMN IF EXISTS deleted_by"
    )
    op.execute(
        "ALTER TABLE channel_messages DROP COLUMN IF EXISTS deleted_at"
    )
    op.execute(
        "ALTER TABLE channel_messages DROP COLUMN IF EXISTS reply_to_message_id"
    )

"""message_reply_state

An inbound message used to be deduped purely by `platform_message_id`. The
row commits before the AI reply, so a crash, an LLM outage or a transient send
failure after that commit left the retry hitting the dedupe check — a no-op
reported as success and a customer who never got an answer.

`ai_reply_status` makes that state explicit: `pending` is re-driven on the next
delivery, and only a terminal status lets the dedupe path return. Attempts and
the last error are kept for diagnosis.

Revision ID: a7c1e9b4d2f60835
Revises: 3d9b7e1a5c204f86
"""

from typing import Sequence, Union

from alembic import op

revision: str = "a7c1e9b4d2f60835"
down_revision: Union[str, None] = "3d9b7e1a5c204f86"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE channel_messages "
        "ADD COLUMN IF NOT EXISTS ai_reply_status VARCHAR(16)"
    )
    op.execute(
        "ALTER TABLE channel_messages "
        "ADD COLUMN IF NOT EXISTS ai_reply_attempts INTEGER NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE channel_messages "
        "ADD COLUMN IF NOT EXISTS ai_reply_error TEXT"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE channel_messages DROP COLUMN IF EXISTS ai_reply_error"
    )
    op.execute(
        "ALTER TABLE channel_messages DROP COLUMN IF EXISTS ai_reply_attempts"
    )
    op.execute(
        "ALTER TABLE channel_messages DROP COLUMN IF EXISTS ai_reply_status"
    )

"""Track Google's moderation state for review replies.

Google moderates review replies (ReviewReplyState, live 2026-04-01): a
submitted reply is PENDING until moderation approves it, and only APPROVED is
public. Sayvors needs the state on the row so the dashboard can show
"awaiting approval" instead of "published" during that window and flip to
published when Google approves.

The state rides the reviews the poll already fetches — no extra API calls.

Revision ID: ff6a7b8c9d0e
Revises: ee5f6a7b8c9d
Create Date: 2026-11-09
"""
from typing import Sequence, Union

from alembic import op

revision: str = "ff6a7b8c9d0e"
down_revision: Union[str, None] = "ee5f6a7b8c9d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE review_replies "
        "ADD COLUMN IF NOT EXISTS google_reply_state VARCHAR(20)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE review_replies DROP COLUMN IF EXISTS google_reply_state")

"""whatsapp_thread_states.preferred_language

The first-contact language choice. Nullable: every existing thread keeps
answering in the detected language until its customer picks one.

Revision ID: bfbad89c36272457
Revises: 227dac0fa4926579
"""

from typing import Sequence, Union

from alembic import op

revision: str = "bfbad89c36272457"
down_revision: Union[str, None] = "227dac0fa4926579"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE whatsapp_thread_states "
        "ADD COLUMN IF NOT EXISTS preferred_language VARCHAR(16)"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE whatsapp_thread_states DROP COLUMN IF EXISTS preferred_language"
    )

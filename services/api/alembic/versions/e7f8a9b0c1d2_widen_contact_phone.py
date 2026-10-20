"""widen contact_phone from varchar(32) to varchar(255)

WhatsApp inbound messages store the Fernet-encrypted contact phone in
contact_phone. Fernet ciphertext is ~60 chars, so varchar(32) truncated
every inbound message with "value too long for type character varying(32)"
and the meta_events_worker could never persist them - the inbox stayed
empty even though the webhook was being received.

Revision ID: e7f8a9b0c1d2
Revises: d2e3f4a5b6c7
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'e7f8a9b0c1d2'
down_revision: Union[str, None] = 'd2e3f4a5b6c7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ALTER COLUMN TYPE is idempotent: re-running on an already-widened
    # column is a no-op at the type level (Postgres keeps the target type).
    op.execute(
        "ALTER TABLE channel_messages "
        "ALTER COLUMN contact_phone TYPE varchar(255) "
        "USING contact_phone::varchar(255)"
    )
    op.execute(
        "ALTER TABLE whatsapp_thread_states "
        "ALTER COLUMN contact_phone TYPE varchar(255) "
        "USING contact_phone::varchar(255)"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE channel_messages "
        "ALTER COLUMN contact_phone TYPE varchar(32) "
        "USING contact_phone::varchar(32)"
    )
    op.execute(
        "ALTER TABLE whatsapp_thread_states "
        "ALTER COLUMN contact_phone TYPE varchar(32) "
        "USING contact_phone::varchar(32)"
    )
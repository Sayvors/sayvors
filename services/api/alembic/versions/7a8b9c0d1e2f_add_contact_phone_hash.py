"""add contact_phone_hash to channel_messages and whatsapp_thread_states

contact_phone_hash exists on the ChannelMessage and WhatsAppThreadState ORM
models but no migration ever created it, so alembic upgrade head silently
skipped it and the inbox thread list crashed with
column contact_phone_hash does not exist.

Revision ID: 7a8b9c0d1e2f
Revises: c69270b5cb92
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '7a8b9c0d1e2f'
down_revision: Union[str, None] = 'c69270b5cb92'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE channel_messages ADD COLUMN IF NOT EXISTS contact_phone_hash varchar(64)"
    )
    op.execute(
        "ALTER TABLE whatsapp_thread_states ADD COLUMN IF NOT EXISTS contact_phone_hash varchar(64)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_channel_messages_contact_phone_hash "
        "ON channel_messages (contact_phone_hash)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_wa_thread_states_contact_phone_hash "
        "ON whatsapp_thread_states (contact_phone_hash)"
    )


def downgrade() -> None:
    op.drop_column('channel_messages', 'contact_phone_hash')
    op.drop_column('whatsapp_thread_states', 'contact_phone_hash')

"""add contact_phone_hash to channel_messages and whatsapp_thread_states

contact_phone_hash exists on the ChannelMessage and WhatsAppThreadState ORM
models but no migration ever created it, so alembic upgrade head silently
skipped it and the inbox thread list crashed with
column contact_phone_hash does not exist.

Revision ID: d4e5f6a7b8c9
Revises: c69270b5cb92
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'c69270b5cb92'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'channel_messages',
        sa.Column('contact_phone_hash', sa.String(length=64), nullable=True, index=True),
    )
    op.add_column(
        'whatsapp_thread_states',
        sa.Column('contact_phone_hash', sa.String(length=64), nullable=True, index=True),
    )


def downgrade() -> None:
    op.drop_column('channel_messages', 'contact_phone_hash')
    op.drop_column('whatsapp_thread_states', 'contact_phone_hash')

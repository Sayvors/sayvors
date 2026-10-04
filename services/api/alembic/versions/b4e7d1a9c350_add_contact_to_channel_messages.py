"""add contact to channel_messages

The inbox groups messages into per-customer threads, but channel_messages never
stored who sent or received a message — the WhatsApp consumer read the sender
and discarded it. These two columns make threading possible.

contact_phone is NULL for rows written before this migration; those are grouped
into a single "Unknown" thread so no conversation text is lost.

Revision ID: b4e7d1a9c350
Revises: a3f19c7d2b84
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b4e7d1a9c350'
down_revision: Union[str, None] = 'a3f19c7d2b84'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('channel_messages', sa.Column('contact_phone', sa.String(length=32), nullable=True))
    op.add_column('channel_messages', sa.Column('contact_name', sa.String(length=120), nullable=True))
    # Serves the inbox thread list: filter to a channel, group by contact, newest
    # message first.
    op.create_index(
        'ix_channel_messages_thread',
        'channel_messages',
        ['channel_id', 'contact_phone', 'created_at'],
    )


def downgrade() -> None:
    op.drop_index('ix_channel_messages_thread', table_name='channel_messages')
    op.drop_column('channel_messages', 'contact_name')
    op.drop_column('channel_messages', 'contact_phone')

"""google reviews channel, auto-reply config, review replies

Revision ID: b7c4d9e2f1a3
Revises: f3b1e7a9d0c2
Create Date: 2026-08-14 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7c4d9e2f1a3'
down_revision: Union[str, None] = 'f3b1e7a9d0c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

PLATFORM_ENUM = 'platform_type'
OLD_VALUES = "('facebook', 'instagram', 'x', 'telegram', 'whatsapp', 'linkedin')"
NEW_VALUES = "('facebook', 'instagram', 'x', 'telegram', 'whatsapp', 'linkedin', 'google_reviews')"


def upgrade() -> None:
    # Add google_reviews to the platform enum.
    # ALTER TYPE ... ADD VALUE cannot run inside a transaction block in
    # Postgres; Alembic's autocommit_block handles that.
    with op.get_context().autocommit_block():
        op.execute(f"ALTER TYPE {PLATFORM_ENUM} ADD VALUE IF NOT EXISTS 'google_reviews'")

    op.create_table(
        'auto_reply_configs',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('channel_id', sa.String(length=36),
                  sa.ForeignKey('channels.id', ondelete='CASCADE'), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('tone', sa.String(length=50), nullable=False, server_default='friendly'),
        sa.Column('databank_id', sa.String(length=36), nullable=True),
        sa.Column('min_rating_auto', sa.Integer(), nullable=False, server_default='4'),
        sa.Column('model', sa.String(length=100), nullable=False,
                  server_default='openai:gpt-4o-mini'),
        sa.Column('last_polled_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('polling_locked_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(op.f('ix_auto_reply_configs_channel_id'),
                    'auto_reply_configs', ['channel_id'], unique=True)
    op.create_index(op.f('ix_auto_reply_configs_databank_id'),
                    'auto_reply_configs', ['databank_id'], unique=False)

    op.create_table(
        'review_replies',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('channel_id', sa.String(length=36),
                  sa.ForeignKey('channels.id', ondelete='CASCADE'), nullable=False),
        sa.Column('review_id', sa.String(length=500), nullable=False),
        sa.Column('rating', sa.Integer(), nullable=False),
        sa.Column('review_text', sa.Text(), nullable=True),
        sa.Column('reviewer_name', sa.String(length=255), nullable=True),
        sa.Column('reply_text', sa.Text(), nullable=False),
        sa.Column('status', sa.Enum('posted', 'pending_approval', 'failed',
                                    name='review_reply_status'),
                  nullable=False, server_default='pending_approval'),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(op.f('ix_review_replies_channel_id'),
                    'review_replies', ['channel_id'], unique=False)
    op.create_index(op.f('ix_review_replies_review_id'),
                    'review_replies', ['review_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_review_replies_review_id'), table_name='review_replies')
    op.drop_index(op.f('ix_review_replies_channel_id'), table_name='review_replies')
    op.drop_table('review_replies')
    op.drop_index(op.f('ix_auto_reply_configs_databank_id'), table_name='auto_reply_configs')
    op.drop_index(op.f('ix_auto_reply_configs_channel_id'), table_name='auto_reply_configs')
    op.drop_table('auto_reply_configs')
    # Note: the added enum value 'google_reviews' cannot be removed from
    # platform_type without recreating the type.
    op.execute(
        f"ALTER TYPE {PLATFORM_ENUM} RENAME TO {PLATFORM_ENUM}_old"
    )
    op.execute(
        f"CREATE TYPE {PLATFORM_ENUM} AS ENUM {OLD_VALUES}"
    )
    op.execute(
        f"ALTER TABLE channels ALTER COLUMN platform TYPE {PLATFORM_ENUM} "
        f"USING platform::text::{PLATFORM_ENUM}"
    )
    op.execute(f"DROP TYPE {PLATFORM_ENUM}_old")

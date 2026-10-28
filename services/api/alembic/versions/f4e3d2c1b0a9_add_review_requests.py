"""add_review_requests

Revision ID: f4e3d2c1b0a9
Revises: 1043cfd670ba
Create Date: 2026-10-28 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'f4e3d2c1b0a9'
down_revision: Union[str, None] = '1043cfd670ba'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'review_requests',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('channel_id', sa.String(length=36), nullable=True),
        sa.Column('contact', sa.String(length=255), nullable=True),
        sa.Column('contact_name', sa.String(length=120), nullable=True),
        sa.Column('channel', sa.String(length=20), server_default='whatsapp', nullable=False),
        sa.Column('trigger', sa.String(length=30), server_default='manual', nullable=False),
        sa.Column('status', sa.String(length=16), server_default='sent', nullable=False),
        sa.Column('sent_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('delivered_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('clicked_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('review_id', sa.String(length=500), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['channel_id'], ['channels.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_review_requests_user_id'), 'review_requests', ['user_id'], unique=False)
    op.create_index(op.f('ix_review_requests_channel_id'), 'review_requests', ['channel_id'], unique=False)
    op.create_index('ix_review_requests_user_sent', 'review_requests', ['user_id', 'sent_at'], unique=False)
    op.create_index('ix_review_requests_user_status', 'review_requests', ['user_id', 'status'], unique=False)
    op.create_index('ix_review_requests_user_channel', 'review_requests', ['user_id', 'channel'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_review_requests_user_channel', table_name='review_requests')
    op.drop_index('ix_review_requests_user_status', table_name='review_requests')
    op.drop_index('ix_review_requests_user_sent', table_name='review_requests')
    op.drop_index(op.f('ix_review_requests_channel_id'), table_name='review_requests')
    op.drop_index(op.f('ix_review_requests_user_id'), table_name='review_requests')
    op.drop_table('review_requests')

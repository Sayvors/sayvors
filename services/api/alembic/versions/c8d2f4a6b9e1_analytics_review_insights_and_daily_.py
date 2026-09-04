"""analytics: review insights + location daily metrics

Revision ID: c8d2f4a6b9e1
Revises: b7c4d9e2f1a3
Create Date: 2026-09-04 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c8d2f4a6b9e1'
down_revision: Union[str, None] = 'b7c4d9e2f1a3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'review_insights',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('channel_id', sa.String(length=36),
                  sa.ForeignKey('channels.id', ondelete='CASCADE'), nullable=False),
        sa.Column('review_id', sa.String(length=500), nullable=False),
        sa.Column('rating', sa.Integer(), nullable=False),
        sa.Column('review_text', sa.Text(), nullable=True),
        sa.Column('reviewer_name', sa.String(length=255), nullable=True),
        sa.Column('sentiment',
                  sa.Enum('positive', 'neutral', 'negative', name='review_sentiment'),
                  nullable=False, server_default='neutral'),
        sa.Column('sentiment_score', sa.Float(), nullable=False, server_default='0'),
        sa.Column('topics', sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column('products', sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column('problems', sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column('enrichment_status',
                  sa.Enum('pending', 'done', 'failed', name='enrichment_status'),
                  nullable=False, server_default='pending'),
        sa.Column('replied', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('replied_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('review_updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('channel_id', 'review_id', name='uq_review_insights_channel_review'),
    )
    op.create_index(op.f('ix_review_insights_user_id'), 'review_insights', ['user_id'], unique=False)
    op.create_index(op.f('ix_review_insights_channel_id'), 'review_insights', ['channel_id'], unique=False)
    op.create_index(op.f('ix_review_insights_review_id'), 'review_insights', ['review_id'], unique=False)
    op.create_index(op.f('ix_review_insights_sentiment'), 'review_insights', ['sentiment'], unique=False)
    op.create_index(op.f('ix_review_insights_enrichment_status'), 'review_insights', ['enrichment_status'], unique=False)

    op.create_table(
        'location_daily_metrics',
        sa.Column('id', sa.String(length=36), primary_key=True),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('channel_id', sa.String(length=36),
                  sa.ForeignKey('channels.id', ondelete='CASCADE'), nullable=False),
        sa.Column('date', sa.Date(), nullable=False),
        sa.Column('reviews_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('avg_rating', sa.Float(), nullable=False, server_default='0'),
        sa.Column('positive_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('neutral_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('negative_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('replies_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('impressions_maps_desktop', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('impressions_maps_mobile', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('website_clicks', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('call_clicks', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('direction_requests', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('extra', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('channel_id', 'date', name='uq_location_daily_channel_date'),
    )
    op.create_index(op.f('ix_location_daily_metrics_user_id'), 'location_daily_metrics', ['user_id'], unique=False)
    op.create_index(op.f('ix_location_daily_metrics_channel_id'), 'location_daily_metrics', ['channel_id'], unique=False)
    op.create_index(op.f('ix_location_daily_metrics_date'), 'location_daily_metrics', ['date'], unique=False)


def downgrade() -> None:
    op.drop_table('location_daily_metrics')
    op.drop_table('review_insights')
    sa.Enum(name='enrichment_status').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='review_sentiment').drop(op.get_bind(), checkfirst=True)

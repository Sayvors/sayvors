"""add_competitor_snapshots

Revision ID: d3e4f5a6b7c8
Revises: f4e3d2c1b0a9
Create Date: 2026-10-28 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'd3e4f5a6b7c8'
down_revision: Union[str, None] = 'f4e3d2c1b0a9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'competitor_snapshots',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('place_id', sa.String(length=255), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('category', sa.String(length=120), nullable=True),
        sa.Column('address', sa.String(length=500), nullable=True),
        sa.Column('rating', sa.Float(), nullable=True),
        sa.Column('review_count', sa.Integer(), nullable=False),
        sa.Column('distance_m', sa.Integer(), nullable=True),
        sa.Column('source', sa.String(length=20), server_default='google_places', nullable=False),
        sa.Column('query_radius_m', sa.Integer(), nullable=True),
        sa.Column('query_category', sa.String(length=120), nullable=True),
        sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', 'place_id', 'source', name='uq_competitor_user_place_source'),
    )
    op.create_index(op.f('ix_competitor_snapshots_user_id'), 'competitor_snapshots', ['user_id'], unique=False)
    op.create_index('ix_competitor_snapshots_user_fetched', 'competitor_snapshots', ['user_id', 'fetched_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_competitor_snapshots_user_fetched', table_name='competitor_snapshots')
    op.drop_index(op.f('ix_competitor_snapshots_user_id'), table_name='competitor_snapshots')
    op.drop_table('competitor_snapshots')

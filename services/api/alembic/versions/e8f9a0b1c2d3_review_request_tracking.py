"""review_request_tracking

Revision ID: e8f9a0b1c2d3
Revises: d3e4f5a6b7c8
Create Date: 2026-10-28 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'e8f9a0b1c2d3'
down_revision: Union[str, None] = 'd3e4f5a6b7c8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('review_requests', sa.Column('token', sa.String(length=64), nullable=True))
    op.add_column('review_requests', sa.Column('review_url', sa.String(length=1024), nullable=True))
    op.add_column('review_requests', sa.Column('sent_via', sa.String(length=20), nullable=True))
    op.add_column('review_requests', sa.Column('error', sa.String(length=300), nullable=True))
    op.create_index('ix_review_requests_token', 'review_requests', ['token'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_review_requests_token', table_name='review_requests')
    op.drop_column('review_requests', 'error')
    op.drop_column('review_requests', 'sent_via')
    op.drop_column('review_requests', 'review_url')
    op.drop_column('review_requests', 'token')

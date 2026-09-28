"""fix_user_feedback_columns

Revision ID: e2d840d74f9b
Revises: a4b5c6d7e8f9
Create Date: 2026-09-28 13:04:14.394796

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e2d840d74f9b'
down_revision: Union[str, None] = 'a4b5c6d7e8f9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('user_feedback', sa.Column('emoji_rating', sa.Integer(), nullable=False, server_default='3'))
    op.add_column('user_feedback', sa.Column('message', sa.Text(), nullable=True))
    op.drop_index('ix_user_feedback_category', table_name='user_feedback')
    op.drop_column('user_feedback', 'category')
    op.drop_column('user_feedback', 'stars')


def downgrade() -> None:
    op.add_column('user_feedback', sa.Column('category', sa.String(length=50), nullable=False))
    op.add_column('user_feedback', sa.Column('stars', sa.Integer(), nullable=False, server_default='0'))
    op.create_index('ix_user_feedback_category', 'user_feedback', ['category'])
    op.drop_column('user_feedback', 'message')
    op.drop_column('user_feedback', 'emoji_rating')

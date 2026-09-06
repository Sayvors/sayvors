"""profile fields on users + user_feedback table

Revision ID: e4f5a6b7c8d9
Revises: d9e8c7b6a5f4
Create Date: 2026-09-06 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e4f5a6b7c8d9'
down_revision: Union[str, None] = 'd9e8c7b6a5f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('bio', sa.Text(), nullable=True))
    op.add_column('users', sa.Column('business_name', sa.String(length=255), nullable=True))
    op.add_column('users', sa.Column('phone', sa.String(length=50), nullable=True))
    op.add_column('users', sa.Column('theme', sa.String(length=20), nullable=False, server_default='light'))
    op.add_column('users', sa.Column('language', sa.String(length=10), nullable=False, server_default='en'))
    op.create_table(
        'user_feedback',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('category', sa.String(length=50), nullable=False),
        sa.Column('stars', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_user_feedback_user_id', 'user_feedback', ['user_id'])
    op.create_index('ix_user_feedback_category', 'user_feedback', ['category'])


def downgrade() -> None:
    op.drop_index('ix_user_feedback_category', table_name='user_feedback')
    op.drop_index('ix_user_feedback_user_id', table_name='user_feedback')
    op.drop_table('user_feedback')
    op.drop_column('users', 'language')
    op.drop_column('users', 'theme')
    op.drop_column('users', 'phone')
    op.drop_column('users', 'business_name')
    op.drop_column('users', 'bio')

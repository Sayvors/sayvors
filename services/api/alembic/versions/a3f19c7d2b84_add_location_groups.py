"""add location_groups

Named sets of listings so bulk actions (details edit, posts, services) can
target "North Riyadh" instead of every branch.

Revises the most recent head (177f1e0bd2a2). The repo already carries four
other independent heads; this does not attempt to merge them.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'a3f19c7d2b84'
down_revision: Union[str, None] = '177f1e0bd2a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'location_groups',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('name', sa.String(length=120), nullable=False),
        sa.Column('listing_ids', sa.JSON(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_location_groups_user_id', 'location_groups', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_location_groups_user_id', table_name='location_groups')
    op.drop_table('location_groups')

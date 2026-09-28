"""drop_updated_at_from_user_feedback

Revision ID: 177f1e0bd2a2
Revises: e2d840d74f9b
Create Date: 2026-09-28 13:09:10.973133

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '177f1e0bd2a2'
down_revision: Union[str, None] = 'e2d840d74f9b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column('user_feedback', 'updated_at')


def downgrade() -> None:
    op.add_column('user_feedback', sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True))

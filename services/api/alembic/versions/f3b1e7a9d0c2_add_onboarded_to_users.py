"""add onboarded to users

Revision ID: f3b1e7a9d0c2
Revises: ceab557d4a2e
Create Date: 2026-08-13 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f3b1e7a9d0c2'
down_revision: Union[str, None] = 'ceab557d4a2e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('users', sa.Column('onboarded', sa.Boolean(), nullable=False, server_default='false'))


def downgrade() -> None:
    op.drop_column('users', 'onboarded')

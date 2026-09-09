"""merge verification and localith snapshot heads

Revision ID: a091b0730d72
Revises: b2c3d4e5f6a7, g7h8i9j0k1l2
Create Date: 2026-09-09 08:57:01.037177

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a091b0730d72'
down_revision: Union[str, None] = ('b2c3d4e5f6a7', 'g7h8i9j0k1l2')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

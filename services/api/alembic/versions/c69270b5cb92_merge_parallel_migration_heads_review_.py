"""merge parallel migration heads (review handoff chain + unified jobs table)

Revision ID: c69270b5cb92
Revises: 20261015090000, z3a4b5c6d7e8
Create Date: 2026-10-18 17:53:20.167253

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c69270b5cb92'
down_revision: Union[str, None] = ('20261015090000', 'z3a4b5c6d7e8')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

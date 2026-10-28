"""review_request_templates

Revision ID: a9b0c1d2e3f4
Revises: e8f9a0b1c2d3
Create Date: 2026-10-28 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'a9b0c1d2e3f4'
down_revision: Union[str, None] = 'e8f9a0b1c2d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('review_requests', sa.Column('subject', sa.String(length=200), nullable=True))
    op.add_column('review_requests', sa.Column('body', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('review_requests', 'body')
    op.drop_column('review_requests', 'subject')

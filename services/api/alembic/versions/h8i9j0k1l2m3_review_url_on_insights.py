"""review_url on review_insights

Revision ID: h8i9j0k1l2m3
Revises: a091b0730d72
Create Date: 2026-09-09 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "h8i9j0k1l2m3"
down_revision: Union[str, None] = "a091b0730d72"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("review_insights", sa.Column("review_url", sa.String(length=1024), nullable=True))


def downgrade() -> None:
    op.drop_column("review_insights", "review_url")

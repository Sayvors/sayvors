"""location_posts event/offer fields: start_date, coupon_code, terms.

Event posts require a start date on Google; offers carry an optional coupon
code (voucherCode) while terms travel inside the caption text (Localith's
wrapper exposes no separate terms field).

Revision ID: g8a9b0c1d2e3
Revises: f7a8b9c0d1e2
Create Date: 2026-09-20 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "g8a9b0c1d2e3"
down_revision: Union[str, None] = "f7a8b9c0d1e2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("location_posts", sa.Column("start_date", sa.DateTime(timezone=True), nullable=True))
    op.add_column("location_posts", sa.Column("coupon_code", sa.String(64), nullable=True))
    op.add_column("location_posts", sa.Column("terms_conditions", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("location_posts", "terms_conditions")
    op.drop_column("location_posts", "coupon_code")
    op.drop_column("location_posts", "start_date")

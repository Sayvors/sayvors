"""review edit tracking on review_insights.

Detects reviewer edits via sync-time content comparison (Localith sends
no edit timestamp): edited flag + detection time + previous text/rating.

Revision ID: w8x9y0z1a2b3
Revises: v7w8x9y0z1a2
Create Date: 2026-09-16 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "w8x9y0z1a2b3"
down_revision: Union[str, None] = "v7w8x9y0z1a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "review_insights",
        sa.Column("edited", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "review_insights",
        sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "review_insights",
        sa.Column("previous_review_text", sa.Text(), nullable=True),
    )
    op.add_column(
        "review_insights",
        sa.Column("previous_rating", sa.Integer(), nullable=True),
    )
    op.create_index("ix_review_insights_edited", "review_insights", ["edited"])


def downgrade() -> None:
    op.drop_index("ix_review_insights_edited", table_name="review_insights")
    op.drop_column("review_insights", "previous_rating")
    op.drop_column("review_insights", "previous_review_text")
    op.drop_column("review_insights", "edited_at")
    op.drop_column("review_insights", "edited")

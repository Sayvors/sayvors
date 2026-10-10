"""Per-post Google metrics: views, CTA clicks, sync timestamp.

Revision ID: c7d9e1f3a5b7
Revises: b9c8d7e6f5a4
Create Date: 2026-10-08

Pulled from Google's localPosts:reportInsights (native OAuth path only —
Localith's API has no post-level metrics). Nullable: NULL means "never
synced", not zero.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "c7d9e1f3a5b7"
down_revision: Union[str, None] = "b9c8d7e6f5a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("location_posts", sa.Column("views", sa.Integer(), nullable=True))
    op.add_column("location_posts", sa.Column("cta_clicks", sa.Integer(), nullable=True))
    op.add_column(
        "location_posts",
        sa.Column("metrics_synced_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("location_posts", "metrics_synced_at")
    op.drop_column("location_posts", "cta_clicks")
    op.drop_column("location_posts", "views")

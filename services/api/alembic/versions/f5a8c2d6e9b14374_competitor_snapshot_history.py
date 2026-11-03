"""Add competitor_snapshot_history for FACT-2.

CompetitorSnapshot keeps the current peer set, but upserting destroyed the
previous cycle: the benchmark could show a peer's current rating but never its
delta. This table appends one row per peer per refresh so the API can compute
rating/review-count deltas and review velocity over time.

The unique constraint prevents a retried refresh from duplicating a cycle.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "f5a8c2d6e9b14374"
down_revision: Union[str, None] = "f5a8c2d6e9b14373"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "competitor_snapshot_history",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("place_id", sa.String(length=255), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("category", sa.String(length=120), nullable=True),
        sa.Column("address", sa.String(length=500), nullable=True),
        sa.Column("rating", sa.Float(), nullable=True),
        sa.Column("review_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source", sa.String(length=20), nullable=False, server_default="google_places"),
        sa.Column("query_radius_m", sa.Integer(), nullable=True),
        sa.Column("query_category", sa.String(length=120), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id", "place_id", "source", "fetched_at",
            name="uq_competitor_history_cycle",
        ),
    )
    op.create_index(
        "ix_competitor_history_user_place_fetched",
        "competitor_snapshot_history",
        ["user_id", "place_id", "fetched_at"],
    )
    op.create_index(
        "ix_competitor_history_user_fetched",
        "competitor_snapshot_history",
        ["user_id", "fetched_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_competitor_history_user_fetched", table_name="competitor_snapshot_history")
    op.drop_index("ix_competitor_history_user_place_fetched", table_name="competitor_snapshot_history")
    op.drop_table("competitor_snapshot_history")

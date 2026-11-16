"""review_problem_issues table

Revision ID: 20261115000000
Revises: 20261114220000
Create Date: 2026-11-15

Tracked AI-detected complaint themes (free-text problem names from review
enrichment). One row per tenant per problem name; the merchant owns the
status (open / in_progress / done / dismissed), and the AI's grounding reads
done/dismissed rows so the assistant knows a complaint was addressed.

The status column uses a real Postgres enum (sa.Enum inside create_table
creates the type), mirroring `location_issues` — the ORM model declares the
same named enum, so inserts cast to the type.
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "20261115000000"
down_revision: Union[str, None] = "20261114220000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "review_problem_issues",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("channel_id", sa.String(36), nullable=True),
        sa.Column("problem", sa.String(255), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False, server_default="medium"),
        sa.Column("mentions_last", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("negative_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("avg_rating", sa.Float(), nullable=False, server_default="0"),
        sa.Column("impact_last", sa.Float(), nullable=False, server_default="0"),
        sa.Column("evidence", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("title", sa.String(200), nullable=False, server_default=""),
        sa.Column("detail", sa.String(400), nullable=False, server_default=""),
        sa.Column(
            "status",
            sa.Enum("open", "in_progress", "done", "dismissed", name="review_problem_issue_status"),
            nullable=False,
            server_default="open",
        ),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("mentions_at_resolve", sa.Integer(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "problem", name="uq_review_problem_issue_user_problem"),
    )
    op.create_index("ix_review_problem_issues_user_status", "review_problem_issues", ["user_id", "status"])
    op.create_index("ix_review_problem_issues_user", "review_problem_issues", ["user_id"])
    op.create_index("ix_review_problem_issues_channel", "review_problem_issues", ["channel_id"])


def downgrade() -> None:
    op.drop_index("ix_review_problem_issues_channel", table_name="review_problem_issues")
    op.drop_index("ix_review_problem_issues_user", table_name="review_problem_issues")
    op.drop_index("ix_review_problem_issues_user_status", table_name="review_problem_issues")
    op.drop_table("review_problem_issues")
    sa.Enum(name="review_problem_issue_status").drop(op.get_bind(), checkfirst=True)

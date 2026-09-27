"""Per-review meaning record on review_insights.

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-09-27

The intelligence report used to receive raw review text and re-interpret it
with a single LLM call. It then turned the Arabic review "you need to fix
your building" into "bank account corrections" and propagated that
fabrication through a theme, an opportunity and a business action.

This column holds the per-review meaning layer that the report now reads
instead: subject (from a CLOSED vocabulary), the customer's intent, the
problem in their own framing, what they are asking for, entities, negation,
verbatim evidence spans, confidence, and whether it needs a human.

source is "llm" | "heuristic" | "human". A human correction is authoritative
and is never overwritten by a re-analysis.

Nullable: rows without a meaning record behave exactly as before.
"""
import sqlalchemy as sa

from alembic import op

revision = "e1f2a3b4c5d6"
down_revision = "d0e1f2a3b4c5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "review_insights",
        sa.Column("meaning", sa.JSON(), nullable=True),
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_review_insights_meaning_needs_human "
        "ON review_insights (((meaning ->> 'needs_human')::boolean)) "
        "WHERE meaning IS NOT NULL AND (meaning ->> 'needs_human') = 'true'"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_review_insights_meaning_subject "
        "ON review_insights ((meaning ->> 'subject')) "
        "WHERE meaning IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_review_insights_meaning_subject")
    op.execute("DROP INDEX IF EXISTS ix_review_insights_meaning_needs_human")
    op.drop_column("review_insights", "meaning")

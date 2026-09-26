"""Abusive-review flagging and AI triage.

Google's Business Profile API has no report/flag endpoint — `reviews` supports
list/get/update/delete (where delete removes YOUR reply) plus `reviewReply`.
There is no way to submit a policy report programmatically, so Sayvors records
the merchant's decision, deep-links them to the exact review in Google's UI,
and tracks that they filed it.

The AI's role is triage only: score how likely a review is to breach Google's
content policies and label why, so a human decides. It never auto-reports and
never auto-publishes, because a false accusation on a public listing is a real
cost to a small business.
"""
import sqlalchemy as sa

from alembic import op

revision = "b8c9d0e1f2a3"
down_revision = "a7b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "review_insights",
        sa.Column("abuse_flagged", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "review_insights", sa.Column("abuse_reported_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("review_insights", sa.Column("abuse_note", sa.Text(), nullable=True))
    op.add_column("review_insights", sa.Column("abuse_score", sa.Float(), nullable=True))
    op.add_column("review_insights", sa.Column("abuse_labels", sa.JSON(), nullable=True))
    op.add_column(
        "review_insights", sa.Column("abuse_verdict", sa.String(32), nullable=True)
    )
    op.add_column(
        "review_insights", sa.Column("abuse_reviewed_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index("ix_review_insights_abuse_flagged", "review_insights", ["abuse_flagged"])
    op.execute("UPDATE review_insights SET abuse_labels = '[]'::json WHERE abuse_labels IS NULL")


def downgrade() -> None:
    op.drop_index("ix_review_insights_abuse_flagged", table_name="review_insights")
    op.drop_column("review_insights", "abuse_reviewed_at")
    op.drop_column("review_insights", "abuse_verdict")
    op.drop_column("review_insights", "abuse_labels")
    op.drop_column("review_insights", "abuse_score")
    op.drop_column("review_insights", "abuse_note")
    op.drop_column("review_insights", "abuse_reported_at")
    op.drop_column("review_insights", "abuse_flagged")

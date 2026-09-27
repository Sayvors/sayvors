"""Add location_issues: a tracked, evidence-backed fix list per location.

"Fix this" on the dashboard linked to the review list, so the dashboard named
a problem and handed back reading material instead of anything to act on. This
table is the thing it should point at: one addressable item per subject per
location, with the fix written from the deterministic playbook, the verbatim
evidence behind it frozen in place, and a status the merchant owns.

Two constraints do real work here:

- `subject` is CHECK-constrained to the meaning layer's closed vocabulary, so a
  category cannot be invented at the storage layer either. Invented categories
  are the failure this whole layer exists to prevent, and it should not be one
  CHECK constraint away from coming back.

- UNIQUE(channel_id, subject) with a single row per subject per location. A
  resolved issue keeps its row rather than being archived, so "did fixing this
  help?" stays answerable by comparing avg_rating around resolved_at.

Forward-only: the earlier revisions are already applied.
"""
import sqlalchemy as sa
from alembic import op

revision = "a4b5c6d7e8f9"
down_revision = "f2a3b4c5d6e7"

# Kept in step with analytics/subjects.py SUBJECT_KEYS. If that vocabulary
# changes, extend this constraint in a new revision — never edit this one.
SUBJECTS = (
    "account_access", "billing_payments", "cleanliness",
    "communication_response", "delivery", "facility_premises",
    "features_updates", "location_access", "other", "product_quality",
    "speed_waiting", "staff_service", "value_pricing",
)


def upgrade() -> None:
    op.create_table(
        "location_issues",
        sa.Column("id", sa.String(36), primary_key=True, nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("channel_id", sa.String(36), nullable=False),
        sa.Column("subject", sa.String(60), nullable=False),
        sa.Column("review_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("negative_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("avg_rating", sa.Float(), nullable=False, server_default="0"),
        sa.Column("evidence", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("title", sa.String(120), nullable=False, server_default=""),
        sa.Column("detail", sa.String(300), nullable=False, server_default=""),
        sa.Column(
            "status",
            sa.Enum("open", "in_progress", "done", "dismissed", name="location_issue_status"),
            nullable=False,
            server_default="open",
        ),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("assignee_kind", sa.String(32), nullable=True),
        sa.Column("assignee_ref", sa.String(120), nullable=True),
        sa.Column("notified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notified_channel", sa.String(32), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("channel_id", "subject", name="uq_location_issue_channel_subject"),
        sa.CheckConstraint(
            "subject IN (" + ", ".join(f"'{s}'" for s in SUBJECTS) + ")",
            name="ck_location_issue_subject_vocab",
        ),
    )
    op.create_index("ix_location_issues_user_id", "location_issues", ["user_id"])
    op.create_index("ix_location_issues_channel_id", "location_issues", ["channel_id"])
    op.create_index("ix_location_issues_subject", "location_issues", ["subject"])
    op.create_index("ix_location_issues_status", "location_issues", ["status"])
    # The list endpoint is always "my issues, worst first" within a scope.
    op.create_index(
        "ix_location_issues_user_channel_status",
        "location_issues",
        ["user_id", "channel_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_location_issues_user_channel_status", table_name="location_issues")
    op.drop_index("ix_location_issues_status", table_name="location_issues")
    op.drop_index("ix_location_issues_subject", table_name="location_issues")
    op.drop_index("ix_location_issues_channel_id", table_name="location_issues")
    op.drop_index("ix_location_issues_user_id", table_name="location_issues")
    op.drop_table("location_issues")
    sa.Enum(name="location_issue_status").drop(op.get_bind(), checkfirst=True)

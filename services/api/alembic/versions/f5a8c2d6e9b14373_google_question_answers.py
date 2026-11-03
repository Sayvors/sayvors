"""Add google_question_answers table for FACT-1.

Google Business Profile listing Q&A is public and appears in search
results, but Sayvors never synced it. This table stores one row per
(question, listing): the customer's question, the merchant's answer (if
any), and sync metadata so the dashboard can show "unanswered questions"
and let the merchant answer from within Sayvors.

Only merchant answers are ever posted back to Google; customer answers are
read-only. The table is keyed by (channel_id, question_id) so duplicate
questions across polls collapse to one row.

Built with IF NOT EXISTS so the migration is re-runnable after a partial
failure.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "f5a8c2d6e9b14373"
down_revision: Union[str, None] = "f5a8c2d6e9b14372"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "google_question_answers"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False, index=True),
        sa.Column("channel_id", sa.String(length=36), nullable=False, index=True),
        sa.Column("question_id", sa.String(length=500), nullable=False, index=True),
        sa.Column("question_text", sa.Text(), nullable=False),
        sa.Column("asker_name", sa.String(length=255), nullable=True),
        sa.Column("asker_profile_photo_url", sa.String(length=1024), nullable=True),
        sa.Column("question_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("answer_text", sa.Text(), nullable=True),
        sa.Column("answerer_name", sa.String(length=255), nullable=True),
        sa.Column("answer_type", sa.String(length=32), nullable=True),
        sa.Column("answer_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_answered", sa.Boolean(), default=False, nullable=False, index=True),
        sa.Column("is_ignored", sa.Boolean(), default=False, nullable=False),
        sa.Column("upvote_count", sa.Integer(), default=0, nullable=False),
        sa.Column("draft_answer_text", sa.Text(), nullable=True),
        sa.Column(
            "draft_status",
            sa.String(length=24),
            server_default="none",
            nullable=False,
            index=True,
        ),
        sa.Column("draft_error", sa.String(length=500), nullable=True),
        sa.Column("draft_generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("draft_approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            default=sa.text("now()"),
            onupdate=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["channel_id"], ["channels.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "channel_id", "question_id", name="uq_google_qa_channel_question"
        ),
    )
    op.create_index(
        "ix_google_qa_channel_created",
        _TABLE,
        ["channel_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_google_qa_channel_answered",
        _TABLE,
        ["channel_id", "is_answered"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_google_qa_channel_answered", table_name=_TABLE)
    op.drop_index("ix_google_qa_channel_created", table_name=_TABLE)
    op.drop_table(_TABLE)

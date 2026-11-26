"""Enforce canonical question uniqueness while allowing resume lineage."""
from alembic import op

revision = "20261126143000"
down_revision = "20261126142000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_ai_visibility_question_canonical "
        "ON ai_visibility_questions (tenant_id, channel_id, normalized_question_hash) "
        "WHERE origin <> 'resume'"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_ai_visibility_question_canonical")

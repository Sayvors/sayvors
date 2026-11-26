"""Allow resumed query sets to carry forward pending question text."""
from alembic import op

revision = "20261126142000"
down_revision = "20261126141000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE ai_visibility_query_sets "
        "ADD COLUMN IF NOT EXISTS adaptive_depth INTEGER NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE ai_visibility_questions "
        "DROP CONSTRAINT IF EXISTS uq_ai_visibility_generated_question_hash"
    )


def downgrade() -> None:
    # Resumed versions legitimately repeat a parent's pending question. Do not
    # restore global text uniqueness: it would reject valid lineage or require
    # destructive deduplication.
    op.execute(
        "ALTER TABLE ai_visibility_query_sets DROP COLUMN IF EXISTS adaptive_depth"
    )

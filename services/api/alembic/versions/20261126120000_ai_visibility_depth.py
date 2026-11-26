"""Add research depth to AI visibility runs."""
from alembic import op

revision = "20261126120000"
down_revision = "20261125130000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE ai_visibility_runs "
        "ADD COLUMN IF NOT EXISTS research_depth VARCHAR(16) NOT NULL DEFAULT 'quick'"
    )
    op.execute(
        "ALTER TABLE plans ADD COLUMN IF NOT EXISTS max_quick_research_month INTEGER"
    )
    op.execute(
        "ALTER TABLE plans ADD COLUMN IF NOT EXISTS max_deep_research_month INTEGER"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE plans DROP COLUMN IF EXISTS max_deep_research_month"
    )
    op.execute(
        "ALTER TABLE plans DROP COLUMN IF EXISTS max_quick_research_month"
    )
    op.execute(
        "ALTER TABLE ai_visibility_runs DROP COLUMN IF EXISTS research_depth"
    )

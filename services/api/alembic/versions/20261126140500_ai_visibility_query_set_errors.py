"""Add terminal error details to AI visibility query sets."""
from alembic import op

revision = "20261126140500"
down_revision = "20261126140000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE ai_visibility_query_sets "
        "ADD COLUMN IF NOT EXISTS failure_code VARCHAR(80)"
    )
    op.execute(
        "ALTER TABLE ai_visibility_query_sets "
        "ADD COLUMN IF NOT EXISTS error TEXT"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE ai_visibility_query_sets DROP COLUMN IF EXISTS error"
    )
    op.execute(
        "ALTER TABLE ai_visibility_query_sets DROP COLUMN IF EXISTS failure_code"
    )

"""Register the business-aware query-set job type in PostgreSQL."""
from alembic import op

revision = "20261126141000"
down_revision = "20261126140500"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "ALTER TYPE job_type ADD VALUE IF NOT EXISTS 'ai_visibility.query_set'"
        )


def downgrade() -> None:
    # PostgreSQL cannot remove an enum value while jobs may reference it.
    # The value is inert after the query-set tables are removed.
    pass

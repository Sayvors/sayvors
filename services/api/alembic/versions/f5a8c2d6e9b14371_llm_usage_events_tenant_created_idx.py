"""Add composite index on llm_usage_events(tenant_id, created_at).

M-9(d): tenant usage rollups and the admin metering page filter one tenant
over a date range and order by created_at. Two single-column indexes forced
a sort of every row for that tenant; the composite serves filter + ORDER BY
together.

Built with CREATE INDEX IF NOT EXISTS so the migration is re-runnable after
a partial failure. On a live table a plain CREATE INDEX holds a write lock
for the whole build; CONCURRENTLY avoids that but cannot run inside a
transaction, so it is used here with autocommit. The table is write-heavy
(one row per LLM call), so CONCURRENTLY is the right choice for production.
"""
from alembic import op

# revision identifiers, used by Alembic.
revision = "f5a8c2d6e9b14371"
down_revision = "f5a8c2d6e9b14370"
branch_labels = None
depends_on = None

_INDEX_NAME = "ix_llm_usage_events_tenant_created"
_TABLE = "llm_usage_events"
_COLUMNS = "tenant_id, created_at"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {_INDEX_NAME} "
            f"ON {_TABLE} ({_COLUMNS})"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {_INDEX_NAME}")

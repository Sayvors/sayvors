"""Give the outbox a producer-supplied dedupe key.

Two writers that retry the same logical event used to enqueue it twice, and
the event was dispatched twice. A nullable UNIQUE column fixes that: rows
without a key are unaffected (NULL is never "equal" in a unique index), and
a key that is set is unique across the table.

Idempotent: re-running against a database that already has the column and
index is a no-op.
"""
from alembic import op

revision = "h2a3b4c5d6e7"
down_revision = "h1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE event_outbox ADD COLUMN IF NOT EXISTS dedupe_key VARCHAR(160)")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_event_outbox_dedupe_key "
        "ON event_outbox (dedupe_key)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_event_outbox_dedupe_key")
    op.execute("ALTER TABLE event_outbox DROP COLUMN IF EXISTS dedupe_key")

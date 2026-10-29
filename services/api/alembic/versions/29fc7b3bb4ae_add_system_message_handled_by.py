"""add system to message_handled_by

The escalation handover line ("Let me get my colleague to help you with
this.") is sent by the AI pipeline but is not an AI answer — it is the AI
stepping aside. It needs its own ``handled_by`` value so analytics do not
count it as a deflection and the inbox can label it honestly.

Revision ID: 29fc7b3bb4ae
Revises: d6e7f8a9b0c1
Create Date: 2026-10-29
"""
from alembic import op

revision = "29fc7b3bb4ae"
down_revision = "d6e7f8a9b0c1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # PostgreSQL 12+ allows ADD VALUE inside a transaction; the new value is
    # committed with the migration and is not used by any statement here, so
    # the "cannot use in the same transaction" restriction does not apply.
    # IF NOT EXISTS keeps a re-run safe on a database that already has it.
    op.execute(
        "ALTER TYPE message_handled_by ADD VALUE IF NOT EXISTS 'system'"
    )


def downgrade() -> None:
    # PostgreSQL cannot drop a single enum value without rebuilding the type
    # and every column that uses it. The value is inert while unused, so a
    # no-op downgrade is safer than a destructive rebuild.
    pass

"""conversation mode on channel_threads

Adds the single authoritative AI/human switch. Before this, "a human owns this
thread" was inferred from ``leads.priority = 'important'`` plus an escalation
clock, which is a one-way mute with no human-facing control.

``mode_changed_by`` separates the automatic escalation (``"system"``) from a
person's decision (a user id, ``"human_reply"``, ``"resolve"``): only the
former may be reversed by the resume sweep.

Revision ID: 6fbcbe8f871b
Revises: 29fc7b3bb4ae
Create Date: 2026-10-29
"""
import sqlalchemy as sa
from alembic import op

revision = "6fbcbe8f871b"
down_revision = "29fc7b3bb4ae"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    # create_type=False on the column plus an explicit create(checkfirst=True):
    # the enum must never be created twice (AGENTS.md §3).
    conversation_mode = sa.Enum("ai", "human", name="conversation_mode")
    conversation_mode.create(bind, checkfirst=True)

    # Existing rows have never been switched, so they are AI-owned until a
    # person says otherwise. The server default backfills them in one pass.
    op.execute(
        "ALTER TABLE channel_threads "
        "ADD COLUMN IF NOT EXISTS conversation_mode conversation_mode "
        "NOT NULL DEFAULT 'ai'"
    )
    op.execute(
        "ALTER TABLE channel_threads "
        "ADD COLUMN IF NOT EXISTS mode_changed_at timestamptz"
    )
    op.execute(
        "ALTER TABLE channel_threads "
        "ADD COLUMN IF NOT EXISTS mode_changed_by varchar(64)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_channel_threads_conversation_mode "
        "ON channel_threads (conversation_mode)"
    )


def downgrade() -> None:
    op.execute(
        "DROP INDEX IF EXISTS ix_channel_threads_conversation_mode"
    )
    op.execute(
        "ALTER TABLE channel_threads DROP COLUMN IF EXISTS mode_changed_by"
    )
    op.execute(
        "ALTER TABLE channel_threads DROP COLUMN IF EXISTS mode_changed_at"
    )
    op.execute(
        "ALTER TABLE channel_threads DROP COLUMN IF EXISTS conversation_mode"
    )
    # Safe only after the column that uses it is gone.
    op.execute("DROP TYPE IF EXISTS conversation_mode")

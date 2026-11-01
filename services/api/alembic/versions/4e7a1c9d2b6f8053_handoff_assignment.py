"""handoff assignment

A handoff used to be a flag (`priority=important` / `conversation_mode=human`)
with no owner. This adds the owner:

* channel_threads.assigned_to — the conversation's human owner, indexed for
  the inbox "mine" filter.
* leads.assigned_to — mirrored from the thread so the leads board, digest and
  escalation email can answer "whose is this?" without a join.
* review_issues.assigned_to — the review ticket queue has its own object; an
  escalated review needs an owner even when it has no inbox thread.

All nullable: every existing thread/ticket starts unassigned, which is the
truthful state — a deploy must not invent owners. ON DELETE SET NULL means
removing a teammate leaves the work unassigned rather than deleting it.

Raw ADD COLUMN IF NOT EXISTS / CREATE INDEX IF NOT EXISTS so a replayed or
partially-applied run cannot collide (Postgres DDL is transactional, but the
guard costs nothing and matches the repo's migration rule).

Revision ID: 4e7a1c9d2b6f8053
Revises: 9b4e2d7c1a6f8035
"""

from typing import Sequence, Union

from alembic import op

revision: str = "4e7a1c9d2b6f8053"
down_revision: Union[str, None] = "9b4e2d7c1a6f8035"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE channel_threads
            ADD COLUMN IF NOT EXISTS assigned_to VARCHAR(36)
            REFERENCES users(id) ON DELETE SET NULL
        """
    )
    op.execute(
        "ALTER TABLE channel_threads ADD COLUMN IF NOT EXISTS assigned_at TIMESTAMPTZ"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_channel_threads_assigned_to "
        "ON channel_threads (assigned_to)"
    )

    op.execute(
        """
        ALTER TABLE leads
            ADD COLUMN IF NOT EXISTS assigned_to VARCHAR(36)
            REFERENCES users(id) ON DELETE SET NULL
        """
    )
    op.execute("ALTER TABLE leads ADD COLUMN IF NOT EXISTS assigned_at TIMESTAMPTZ")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_leads_tenant_assigned "
        "ON leads (tenant_id, assigned_to)"
    )

    op.execute(
        """
        ALTER TABLE review_issues
            ADD COLUMN IF NOT EXISTS assigned_to VARCHAR(36)
            REFERENCES users(id) ON DELETE SET NULL
        """
    )
    op.execute(
        "ALTER TABLE review_issues ADD COLUMN IF NOT EXISTS assigned_at TIMESTAMPTZ"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_review_issues_tenant_assigned "
        "ON review_issues (tenant_id, assigned_to)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_review_issues_tenant_assigned")
    op.execute("ALTER TABLE review_issues DROP COLUMN IF EXISTS assigned_at")
    op.execute("ALTER TABLE review_issues DROP COLUMN IF EXISTS assigned_to")

    op.execute("DROP INDEX IF EXISTS ix_leads_tenant_assigned")
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS assigned_at")
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS assigned_to")

    op.execute("DROP INDEX IF EXISTS ix_channel_threads_assigned_to")
    op.execute("ALTER TABLE channel_threads DROP COLUMN IF EXISTS assigned_at")
    op.execute("ALTER TABLE channel_threads DROP COLUMN IF EXISTS assigned_to")

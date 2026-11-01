"""conversation_memories + users.ai_memory_enabled

Cumulative memory: a resolved conversation produces one pending memory
(summary, outcome, extracted facts). A human approves or rejects it in the
review queue; only approved rows are retrievable. Nothing is backfilled:
there is no historical memory to invent.

The toggle lives on the workspace owner (`users.ai_memory_enabled`), because
memory is tenant-wide knowledge, not a per-agent preference. Default true:
pending rows change no behaviour until approved.

Revision ID: 7c2f9b4e1d6a8035
Revises: 4e7a1c9d2b6f8053
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "7c2f9b4e1d6a8035"
down_revision: Union[str, None] = "4e7a1c9d2b6f8053"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_STATUS = sa.Enum(
    "pending", "approved", "rejected", name="memory_status"
)


def upgrade() -> None:
    bind = op.get_bind()
    _STATUS.create(bind, checkfirst=True)

    op.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS "
        "ai_memory_enabled BOOLEAN NOT NULL DEFAULT true"
    )
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS conversation_memories (
            id VARCHAR(36) PRIMARY KEY,
            tenant_id VARCHAR(36) NOT NULL,
            channel_id VARCHAR(36) NOT NULL,
            source_context_id VARCHAR(36)
                REFERENCES conversation_contexts(id) ON DELETE SET NULL,
            summary TEXT NOT NULL,
            outcome VARCHAR(300),
            facts JSON,
            status memory_status NOT NULL DEFAULT 'pending',
            model VARCHAR(100),
            reviewed_by VARCHAR(36),
            reviewed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_conversation_memories_tenant_id "
        "ON conversation_memories (tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_memories_tenant_status_created "
        "ON conversation_memories (tenant_id, status, created_at)"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_memories_source_context "
        "ON conversation_memories (source_context_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_memories_source_context")
    op.execute("DROP INDEX IF EXISTS ix_memories_tenant_status_created")
    op.execute("DROP INDEX IF EXISTS ix_conversation_memories_tenant_id")
    op.execute("DROP TABLE IF EXISTS conversation_memories")
    op.execute(
        "ALTER TABLE users DROP COLUMN IF EXISTS ai_memory_enabled"
    )
    bind = op.get_bind()
    _STATUS.drop(bind, checkfirst=True)

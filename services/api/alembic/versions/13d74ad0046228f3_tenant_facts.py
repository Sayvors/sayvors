"""tenant_facts

The AI's central business-facts row: identity, contact, services, team and
every location's hours, read through the `get_business_facts` tool instead of
querying nine tables per reply.

Additive and empty on apply: a missing row is rebuilt on the next read, so
existing tenants are populated lazily and nothing is backfilled here.

Revision ID: 13d74ad0046228f3
Revises: bfbad89c36272457
"""

from typing import Sequence, Union

from alembic import op

revision: str = "13d74ad0046228f3"
down_revision: Union[str, None] = "bfbad89c36272457"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS tenant_facts (
            tenant_id VARCHAR(36) PRIMARY KEY
                REFERENCES users(id) ON DELETE CASCADE,
            facts JSONB NOT NULL DEFAULT '{}'::jsonb,
            version INTEGER NOT NULL DEFAULT 1,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS tenant_facts")

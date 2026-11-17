"""enterprise_request_recipients: sales emails for Enterprise requests

Revision ID: 20261117100000
Revises: 20261116120000
Create Date: 2026-11-17

A tenant asking for the Enterprise plan emails a configured list of people so
sales can follow up. The list is platform-level and managed from the admin
console, so it lives beside the other admin config tables. Addresses are stored
normalized and unique; the admin UI adds/removes one row at a time. Idempotent
DDL so a staging re-run cannot fail on an existing table.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20261117100000"
down_revision: Union[str, None] = "20261116120000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS enterprise_request_recipients (
            id VARCHAR(36) PRIMARY KEY,
            email VARCHAR(320) NOT NULL,
            created_by VARCHAR(64),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_enterprise_request_recipients_email "
        "ON enterprise_request_recipients (email)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS enterprise_request_recipients")

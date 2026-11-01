"""lead_tickets

Make the WhatsApp lead the ticket record for the conversation, with the sales
qualification kept as fields inside it:

* ticket_number — human-facing, stable, unique per tenant
* ticket_status — work lifecycle (new/open/in_progress/resolved/closed)
* ticket_kind — support | sales | info | general
* resolved_at — when the ticket left the queue

Existing rows keep NULL ticket_number and the default status; new capture and
the migration backfill script give them identity. The leads table is the ticket
table on purpose: one work object, not a parallel lead/ticket split.

Revision ID: f3a6c8e1d4b97520
Revises: d4f7a1c9e2b65083
"""

from typing import Sequence, Union

from alembic import op

revision: str = "f3a6c8e1d4b97520"
down_revision: Union[str, None] = "d4f7a1c9e2b65083"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE leads ADD COLUMN IF NOT EXISTS ticket_number VARCHAR(20)"
    )
    op.execute(
        "ALTER TABLE leads ADD COLUMN IF NOT EXISTS ticket_status "
        "VARCHAR(20) NOT NULL DEFAULT 'new'"
    )
    op.execute(
        "ALTER TABLE leads ADD COLUMN IF NOT EXISTS ticket_kind "
        "VARCHAR(30) NOT NULL DEFAULT 'whatsapp_general'"
    )
    op.execute(
        "ALTER TABLE leads ADD COLUMN IF NOT EXISTS resolved_at TIMESTAMPTZ"
    )
    # Backfill every existing lead: a lead is a ticket, so it needs identity
    # and a status that matches the sales stage it already carries.
    op.execute(
        "UPDATE leads SET ticket_number = 'WA-' || "
        "UPPER(SUBSTR(REPLACE(id, '-', ''), 1, 16)) "
        "WHERE ticket_number IS NULL"
    )
    op.execute(
        "UPDATE leads SET ticket_kind = CASE "
        "WHEN category = 'support' THEN 'whatsapp_support' "
        "WHEN category IN ('wholesale','retail','booking','quote') "
        "THEN 'whatsapp_sales' "
        "WHEN category = 'info' THEN 'whatsapp_info' "
        "ELSE 'whatsapp_general' END"
    )
    op.execute(
        "UPDATE leads SET ticket_status = CASE stage "
        "WHEN 'qualified' THEN 'open' "
        "WHEN 'follow_up' THEN 'in_progress' "
        "WHEN 'converted' THEN 'resolved' "
        "WHEN 'lost' THEN 'closed' "
        "ELSE 'new' END"
    )
    op.execute(
        "UPDATE leads SET ticket_status = 'open' "
        "WHERE priority = 'important' AND ticket_status = 'new'"
    )
    op.execute(
        "UPDATE leads SET resolved_at = updated_at "
        "WHERE stage = 'converted' AND resolved_at IS NULL"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS ix_leads_tenant_ticket "
        "ON leads (tenant_id, ticket_number)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_leads_tenant_ticket_status "
        "ON leads (tenant_id, ticket_status)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_leads_tenant_ticket_status")
    op.execute("DROP INDEX IF EXISTS ix_leads_tenant_ticket")
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS resolved_at")
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS ticket_kind")
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS ticket_status")
    op.execute("ALTER TABLE leads DROP COLUMN IF EXISTS ticket_number")

"""Add lead escalation state.

Revision ID: 20261013140000
Revises: 20261013120000
Create Date: 2026-10-13

See docs/specs/2026-10-13-lead-priority-escalation-design.md.

Defaults are the non-escalated state, so existing rows backfill to
ai_miss_count=0 / priority='normal' and no tenant is escalated by a deploy.

ix_leads_pending_reminder is a PARTIAL index (WHERE priority='important').
It is created with raw SQL rather than op.create_index because a partial
index cannot be expressed in the portable __table_args__ form, and SQLite
cannot represent one at all. The reminder sweep is the only cross-tenant
query in this feature; without it that sweep scans every lead row on
every 15s tick.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261013140000"
down_revision: Union[str, Sequence[str], None] = "20261013120000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PRIORITY = sa.Enum("normal", "important", name="lead_priority")

_NEW_COLUMNS = (
    "ai_miss_count",
    "priority",
    "priority_since",
    "escalated_at",
    "escalation_reminder_at",
    "handover_sent_at",
)


def upgrade() -> None:
    bind = op.get_bind()
    # SQLite has no native partial index. Skip there rather than emit SQL it
    # would reject; the application query stays correct either way.
    is_postgres = bind.dialect.name == "postgresql"

    _PRIORITY.create(bind, checkfirst=True)
    op.add_column(
        "leads", sa.Column("ai_miss_count", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column("leads", sa.Column("priority", _PRIORITY, nullable=False, server_default="normal"))
    op.add_column("leads", sa.Column("priority_since", sa.DateTime(timezone=True), nullable=True))
    op.add_column("leads", sa.Column("escalated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("leads", sa.Column("escalation_reminder_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("leads", sa.Column("handover_sent_at", sa.DateTime(timezone=True), nullable=True))

    op.create_index(
        "ix_leads_tenant_priority",
        "leads",
        ["tenant_id", "priority", "updated_at"],
        unique=False,
    )

    if is_postgres:
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_leads_pending_reminder "
            "ON leads (escalation_reminder_at) WHERE priority = 'important'"
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP INDEX IF EXISTS ix_leads_pending_reminder")
    op.drop_index("ix_leads_tenant_priority", table_name="leads")
    for col in reversed(_NEW_COLUMNS):
        op.drop_column("leads", col)
    _PRIORITY.drop(bind, checkfirst=True)
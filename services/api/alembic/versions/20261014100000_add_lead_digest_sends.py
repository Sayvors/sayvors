"""Add lead_digest_sends — the once-per-day marker for the pending-leads digest.

Revision ID: 20261014100000
Revises: 20261013141000
Create Date: 2026-10-14

Why a table rather than a timestamp on the settings JSON: idempotency has to
be structural. The digest sweep can run on several workers at once and can
restart mid-send, and "email the tenant once a day" must not mean "email them
however many times the sweep happens to fire". UNIQUE (tenant_id, digest_date)
makes a duplicate physically impossible, so the guard needs no lock and no
read-then-write race.

digest_date is the tenant's LOCAL date, not a UTC timestamp: a tenant in
Riyadh should get their digest on their morning, and storing the resolved
date makes "have I sent today's digest?" answerable with one indexed lookup.

Nothing here backfills — no tenant has received a digest yet, and a deploy
must not email anyone.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "20261014100000"
down_revision: Union[str, Sequence[str], None] = "20261013141000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "lead_digest_sends",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        # The tenant's local calendar date (YYYY-MM-DD).
        sa.Column("digest_date", sa.Date, nullable=False),
        # How many leads the email listed. Kept so a report can show history
        # without reconstructing it, and so a 0-lead send is visibly a bug
        # rather than a silent nothing.
        sa.Column("lead_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        # The idempotency guarantee. Without this the sweep is a race.
        sa.UniqueConstraint(
            "tenant_id", "digest_date", name="uq_lead_digest_sends_tenant_date"
        ),
    )
    # The sweep's only cross-tenant query: "which tenants have pending leads
    # and have not been digested today". Both columns are in the unique
    # constraint, so this is a covering index for free.
    op.create_index(
        "ix_lead_digest_sends_tenant_date",
        "lead_digest_sends",
        ["tenant_id", "digest_date"],
    )


def downgrade() -> None:
    op.drop_index("ix_lead_digest_sends_tenant_date", table_name="lead_digest_sends")
    op.drop_table("lead_digest_sends")
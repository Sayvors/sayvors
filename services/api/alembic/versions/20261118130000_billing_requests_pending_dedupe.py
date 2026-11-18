"""One pending billing request per tenant/kind/amount/plan.

The 24h dedupe in requests.create_request is a read-then-write. Two clicks in
the same instant both pass the SELECT and both insert, leaving the operator
two identical requests to review. This migration makes the database the
arbiter with a partial unique index, after folding any duplicates that the
old race already created into a single live pending row.

Revision ID: 20261118130000
Revises: 20261117120000
Create Date: 2026-11-18
"""
from typing import Sequence, Union

from alembic import op

revision: str = "20261118130000"
down_revision: Union[str, None] = "20261117120000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Distinctive so the downgrade cannot revive a status another feature owns.
DUPLICATE_STATUS = "expired_dedupe"


def upgrade() -> None:
    # A deployment that already hit the race cannot create the index until
    # the duplicates are collapsed. Keep the newest row (the one an operator
    # is most likely to act on) and retire the rest, newest-first tie broken
    # by id so the result is deterministic across replicas and re-runs.
    op.execute(
        f"""
        WITH ranked AS (
            SELECT id,
                   row_number() OVER (
                       PARTITION BY tenant_id, kind,
                                    COALESCE(amount, -1),
                                    COALESCE(plan_slug, '')
                       WHERE status = 'pending'
                       ORDER BY created_at DESC, id DESC
                   ) AS rn
            FROM billing_requests
        )
        UPDATE billing_requests AS br
        SET status = '{DUPLICATE_STATUS}'
        FROM ranked
        WHERE ranked.id = br.id AND ranked.rn > 1
        """
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_billing_requests_pending_dedupe "
        "ON billing_requests "
        "(tenant_id, kind, COALESCE(amount, -1), COALESCE(plan_slug, '')) "
        "WHERE status = 'pending'"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_billing_requests_pending_dedupe")
    op.execute(
        f"UPDATE billing_requests SET status = 'pending' "
        f"WHERE status = '{DUPLICATE_STATUS}'"
    )

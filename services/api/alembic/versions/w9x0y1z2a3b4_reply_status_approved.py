"""Add 'approved' to the review_reply_status enum.

Revision ID: w9x0y1z2a3b4
Revises: v8w9x0y1z2a3
Create Date: 2026-09-21

The model gained 'approved' (merchant-approved Localith draft) but only a
hand-run ALTER on dev added it to Postgres — no migration. Any query
mentioning the value (e.g. the Localith sync's latest-reply lookup with
IN (..., 'approved')) fails on such DBs with:
  invalid input value for enum review_reply_status: "approved"
New enum values cannot be added inside a transaction block, hence the
autocommit block (same pattern as d9e8c7b6a5f4).
"""
from alembic import op

revision = "w9x0y1z2a3b4"
down_revision = "v8w9x0y1z2a3"
branch_labels = None
depends_on = None

STATUS_ENUM = "review_reply_status"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            f"ALTER TYPE {STATUS_ENUM} ADD VALUE IF NOT EXISTS 'approved'"
        )


def downgrade() -> None:
    # Postgres cannot drop a single enum value; recreating the type would
    # rewrite every row. The value stays — harmless when unused.
    pass

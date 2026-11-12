"""single-use handoff code redemption (used_at + spending wamid)

Revision ID: 20261112130000
Revises: 20261112120000
Create Date: 2026-11-12

Option B of the handoff hardening (§17b): a matched code is consumed on first
redemption, closing the replay window for published codes. The spending
message's wamid is recorded so a Meta webhook redelivery of the same message
still resolves — a duplicate delivery must never drop a real customer.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20261112130000"
down_revision: Union[str, None] = "20261112120000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE review_issues ADD COLUMN IF NOT EXISTS "
        "handoff_code_used_at TIMESTAMP WITH TIME ZONE"
    )
    op.execute(
        "ALTER TABLE review_issues ADD COLUMN IF NOT EXISTS "
        "handoff_code_used_by_wamid VARCHAR(64)"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE review_issues DROP COLUMN IF EXISTS handoff_code_used_at"
    )
    op.execute(
        "ALTER TABLE review_issues DROP COLUMN IF EXISTS handoff_code_used_by_wamid"
    )

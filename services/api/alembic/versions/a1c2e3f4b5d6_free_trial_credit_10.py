"""Set the free-trial plan to the $10 launch credit.

The original seed carried $50. Product decision: every new tenant starts on
the free trial with $10 of AI credit until they choose another plan. The
signup grant reads ``TRIAL_CREDIT_CENTS`` (also $10); this keeps the plan card
and the actual wallet aligned.

Revision ID: a1c2e3f4b5d6
Revises: f4b7c2a9d1e8
Create Date: 2026-11-04
"""
from typing import Sequence, Union

from alembic import op

revision: str = "a1c2e3f4b5d6"
down_revision: Union[str, None] = "f4b7c2a9d1e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Only correct the untouched launch seed. If an operator has deliberately
    # changed the trial credit since, leave their value alone.
    op.execute(
        "UPDATE plans SET included_credit_cents = 1000 "
        "WHERE slug = 'free-trial' AND included_credit_cents = 5000"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE plans SET included_credit_cents = 5000 "
        "WHERE slug = 'free-trial' AND included_credit_cents = 1000"
    )

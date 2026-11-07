"""Free Trial: 500 monthly messages instead of 1,000.

Product decision to tighten the launch allowance. Guarded on the previous
value so an operator who already edited the plan keeps their number.

Revision ID: d1f2a3b4c5e6
Revises: a9b0c1d2e3f5
Create Date: 2026-11-07
"""
from typing import Sequence, Union

from alembic import op

revision: str = "d1f2a3b4c5e6"
down_revision: Union[str, None] = "a9b0c1d2e3f5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "UPDATE plans SET max_messages_per_month = 500, updated_at = now() "
        "WHERE slug = 'free-trial' AND max_messages_per_month = 1000"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE plans SET max_messages_per_month = 1000, updated_at = now() "
        "WHERE slug = 'free-trial' AND max_messages_per_month = 500"
    )

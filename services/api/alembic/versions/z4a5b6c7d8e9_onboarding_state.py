"""per-user onboarding checklist state

Revision ID: z4a5b6c7d8e9
Revises: b6c7d8e9f0a1
Create Date: 2026-10-25

Persists the "Start here — launch step by step" checklist (which steps are
done, collapsed/expanded, dismissed) in the database so it is consistent
across devices instead of living only in localStorage.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "z4a5b6c7d8e9"
down_revision: Union[str, None] = "b6c7d8e9f0a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS onboarding_state JSON"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE users DROP COLUMN IF EXISTS onboarding_state"
    )

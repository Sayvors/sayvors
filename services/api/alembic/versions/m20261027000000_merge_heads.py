"""Merge all migration heads into a single head.

Revision ID: m20261027000000
Revises: 20261012095937, 20261026090000, c3f8a1d6e9b4, g7h8i9j0k1l2, t6u7v8w9x0y1, z3a4b5c6d7e8
Create Date: 2026-10-27

The migration graph had six independent heads (parallel feature work on
channels, analytics, billing, jobs, onboarding, search). `alembic upgrade head`
applied all of them, but the split made every new migration ambiguous: a
revision could only chain off one head, leaving the others dangling and
forcing each deploy to reconcile multiple heads by hand.

This is a no-op merge revision: it performs no schema changes. Its sole
purpose is to give the graph a single head again, so subsequent migrations
(one revision per logical change) chain cleanly off it and `alembic heads`
reports exactly one revision.

After this lands, all new migrations must use down_revision = "m20261027000000".
"""

from typing import Sequence, Union

from alembic import op

revision: str = "m20261027000000"
down_revision: Union[str, Sequence[str], None] = (
    "20261012095937",
    "20261026090000",
    "c3f8a1d6e9b4",
    "g7h8i9j0k1l2",
    "t6u7v8w9x0y1",
    "z3a4b5c6d7e8",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # No-op merge: ties the six heads together.
    pass


def downgrade() -> None:
    # No-op.
    pass

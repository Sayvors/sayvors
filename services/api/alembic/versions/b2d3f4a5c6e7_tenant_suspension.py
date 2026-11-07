"""Add platform-level tenant suspension.

Admins can suspend a workspace from the console. Suspension is stored on the
owner row; employees inherit it through tenant_id. The columns are nullable so
existing rows are active by definition.

Revision ID: b2d3f4a5c6e7
Revises: a1c2e3f4b5d6
Create Date: 2026-11-07
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b2d3f4a5c6e7"
down_revision: Union[str, None] = "a1c2e3f4b5d6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS suspended_at TIMESTAMPTZ")
    op.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS suspension_reason VARCHAR(300)"
    )
    # Admin listings filter on suspension; the partial index keeps that cheap
    # without indexing the (majority) NULL rows.
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_users_suspended_at "
        "ON users (suspended_at) WHERE suspended_at IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_users_suspended_at")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS suspension_reason")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS suspended_at")

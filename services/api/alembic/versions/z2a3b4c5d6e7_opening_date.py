"""Opening date on location_profiles (Google openInfo.openingDate).

Revision ID: z2a3b4c5d6e7
Revises: y1z2a3b4c5d6
Create Date: 2026-09-21

Nullable date — older rows simply have none; the locations UI offers an
"Opening date" field and the native Google path pushes it.
"""
import sqlalchemy as sa
from sqlalchemy import text

from alembic import op

revision = "z2a3b4c5d6e7"
down_revision = "y1z2a3b4c5d6"
branch_labels = None
depends_on = None


def _table_exists() -> bool:
    return op.get_bind().execute(
        text("SELECT to_regclass('location_profiles')")
    ).scalar() is not None


def upgrade() -> None:
    # This revision lives on a branch that Alembic may apply before the
    # branch that creates location_profiles (k1l2m3n4o5p6). A fresh database
    # must not fail on the ordering; the column is part of that CREATE, and
    # on a database where the table already exists this adds it idempotently.
    if not _table_exists():
        return
    op.execute(
        "ALTER TABLE location_profiles "
        "ADD COLUMN IF NOT EXISTS opening_date DATE"
    )


def downgrade() -> None:
    if not _table_exists():
        return
    op.execute("ALTER TABLE location_profiles DROP COLUMN IF EXISTS opening_date")

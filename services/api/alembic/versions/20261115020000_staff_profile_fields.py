"""staff profile fields: avatar, contact, job title, bio

Revision ID: 20261115020000
Revises: 20261115010000
Create Date: 2026-11-15

The employee registry (§33) was created with just enough for review matching:
name, branch and aliases. The per-employee profile page needs a face and a way
to reach the person, so this adds optional merchant-entered profile fields.

Every statement is ``IF NOT EXISTS`` so the migration is safe to re-run on a
database that already has some of the columns (a partially applied deploy, or a
models-only rebuild followed by ``alembic upgrade head``).
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20261115020000"
down_revision: Union[str, None] = "20261115010000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COLUMNS = (
    ("avatar_url", "VARCHAR(1000)"),
    ("avatar_storage_key", "VARCHAR(500)"),
    ("phone", "VARCHAR(50)"),
    ("email", "VARCHAR(255)"),
    ("job_title", "VARCHAR(120)"),
    ("bio", "TEXT"),
)


def upgrade() -> None:
    for name, sql_type in _COLUMNS:
        op.execute(
            f"ALTER TABLE staff_members ADD COLUMN IF NOT EXISTS {name} {sql_type}"
        )


def downgrade() -> None:
    for name, _ in reversed(_COLUMNS):
        op.execute(f"ALTER TABLE staff_members DROP COLUMN IF EXISTS {name}")
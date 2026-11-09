"""Give newsletter campaigns a human-readable name.

The subject is customer-facing and often long; the admin list needs a short
label ("Weekly updates", "October launch"). Existing campaigns inherit their
subject so nothing renders blank.

Revision ID: ee5f6a7b8c9d
Revises: dd4e5f6a7b8c
Create Date: 2026-11-08
"""
from typing import Sequence, Union

from alembic import op

revision: str = "ee5f6a7b8c9d"
down_revision: Union[str, None] = "dd4e5f6a7b8c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE email_campaigns "
        "ADD COLUMN IF NOT EXISTS name VARCHAR(120) NOT NULL DEFAULT ''"
    )
    op.execute(
        "UPDATE email_campaigns "
        "SET name = LEFT(subject, 120) "
        "WHERE name = ''"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE email_campaigns DROP COLUMN IF EXISTS name")

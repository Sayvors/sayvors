"""banner_decision_model on platform_config.

Revision ID: 20261121120000
Revises: 20261119160000
Create Date: 2026-11-21

The banner check gains an optional *decision* model: a plain text LLM that
reads the deterministic rule measurements (and the vision verdict, when one
exists) and writes the final yes/maybe/no in plain language. Any enabled
model qualifies — no vision capability required. NULL keeps the built-in
weighted scoring.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261121120000"
down_revision: Union[str, None] = "20261119160000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE platform_config "
        "ADD COLUMN IF NOT EXISTS banner_decision_model TEXT"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE platform_config DROP COLUMN IF EXISTS banner_decision_model")

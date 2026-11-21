"""supports_vision flag on llm_model_configs.

Revision ID: 20261119160000
Revises: 20261119150000
Create Date: 2026-11-19

Catalog models get their vision capability from code (ModelInfo.supports_vision).
Custom models store it in this column; NULL means "no vision support declared".
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20261119160000"
down_revision: Union[str, None] = "20261119150000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "llm_model_configs",
        sa.Column("supports_vision", sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("llm_model_configs", "supports_vision")

"""Per-language voice pins on voice engines.

Revision ID: f1a2b3c4d5e6
Revises: e0f1a2b3c4d5
Create Date: 2026-10-03

voice_model_configs.language_references: optional JSON map
{"ur": "<reference_id>", "ar": ...}. A pin for the customer's language
overrides the engine's multilingual reference_id; absent = one voice for
all languages.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, None] = "e0f1a2b3c4d5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "voice_model_configs",
        sa.Column("language_references", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("voice_model_configs", "language_references")
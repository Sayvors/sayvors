"""custom model definition columns on llm_model_configs

Revision ID: o5p6q7r8s9t0
Revises: n4o5p6q7r8s9
Create Date: 2026-09-10 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "o5p6q7r8s9t0"
down_revision: Union[str, None] = "n4o5p6q7r8s9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("llm_model_configs", sa.Column("display_name", sa.String(length=120), nullable=True))
    op.add_column("llm_model_configs", sa.Column("provider", sa.String(length=32), nullable=True))
    op.add_column("llm_model_configs", sa.Column("api_model", sa.String(length=200), nullable=True))
    op.add_column("llm_model_configs", sa.Column("context_window", sa.Integer(), nullable=True))
    op.add_column("llm_model_configs", sa.Column("max_output", sa.Integer(), nullable=True))
    op.add_column("llm_model_configs", sa.Column("supports_stream", sa.Boolean(), nullable=True))


def downgrade() -> None:
    for col in ("supports_stream", "max_output", "context_window", "api_model", "provider", "display_name"):
        op.drop_column("llm_model_configs", col)

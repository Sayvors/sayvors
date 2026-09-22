"""Per-connection Localith API key (P1: stop sharing one env key).

Revision ID: b5c6d7e8f9a0
Revises: a3b4c5d6e7f8
Create Date: 2026-09-22
"""
import sqlalchemy as sa

from alembic import op

revision = "b5c6d7e8f9a0"
down_revision = "b4c5d6e7f8a9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "localith_connections",
        sa.Column("api_key_encrypted", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("localith_connections", "api_key_encrypted")

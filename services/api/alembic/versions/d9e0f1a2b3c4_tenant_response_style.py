"""Tenant response style for WhatsApp message rendering.

Revision ID: d9e0f1a2b3c4
Revises: c7d8e9f0a1b2
Create Date: 2026-10-03

Adds users.response_style — how the WhatsApp response renderer delivers one
logical AI response ("concise" = single message, "human" = 1..N natural
messages). Extensible string enum; existing tenants default to "concise",
which reproduces today's single-message behaviour exactly.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "d9e0f1a2b3c4"
down_revision: Union[str, None] = "c7d8e9f0a1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "response_style",
            sa.String(length=16),
            nullable=False,
            server_default="concise",
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "response_style")

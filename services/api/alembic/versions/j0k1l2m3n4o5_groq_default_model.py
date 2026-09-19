"""groq default reply model

Revision ID: j0k1l2m3n4o5
Revises: i9j0k1l2m3n4
Create Date: 2026-09-09 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "j0k1l2m3n4o5"
down_revision: Union[str, None] = "i9j0k1l2m3n4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "UPDATE auto_reply_configs SET model = 'groq:oss-120b' "
        "WHERE model = 'openai:gpt-4o-mini'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE auto_reply_configs SET model = 'openai:gpt-4o-mini' "
        "WHERE model = 'groq:oss-120b'"
    )

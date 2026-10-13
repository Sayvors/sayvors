"""Add users.typing_indicator.

Revision ID: 20261013120000
Revises: 20261013091500
Create Date: 2026-10-13

The "Typing Indicator" toggle on the channel settings page was plain React
useState — never persisted, never sent anywhere, so turning it off did
nothing while the UI implied it had. Persisted as a real tenant setting so the
consumer can honour it before calling send_typing_indicator.

server_default=True because that was the (cosmetic) default the toggle
showed, and existing rows should keep receiving the dots rather than silently
losing them at deploy time. NULL is never written.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20261013120000"
down_revision: Union[str, Sequence[str], None] = "20261013091500"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "typing_indicator",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "typing_indicator")
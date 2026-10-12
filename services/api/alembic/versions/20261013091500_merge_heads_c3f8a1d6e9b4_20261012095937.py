"""Merge the two divergent revision branches into a single head.

Revision ID: 20261013091500
Revises: c3f8a1d6e9b4, 20261012095937
Create Date: 2026-10-13

`alembic heads` reported two heads, both branching off b7d6e5f4a3c2:

  c3f8a1d6e9b4  notification_settings (users.notification_settings)
  20261012095937 meta events worker lease columns (event_outbox)

Because of the split, `alembic upgrade head` aborted with "Multiple head
revisions are present", so neither branch could be applied and the DB stayed
at b7d6e5f4a3c2 while the User model already declared notification_settings.
Every read of `users` then failed with UndefinedColumnError, which surfaced
in the frontend as "Unexpected token 'I', "Internal S"... is not valid JSON".

This is a pure merge: no schema change, only a join point so `upgrade head`
applies both branches.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "20261013091500"
down_revision: Union[str, Sequence[str], None] = (
    "c3f8a1d6e9b4",
    "20261012095937",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
"""Tenant notification (live-toast) settings.

Revision ID: c3f8a1d6e9b4
Revises: b7d6e5f4a3c2
Create Date: 2026-10-11

`users.notification_settings` — which realtime notifications a tenant
wants popped as dashboard toasts (new messages, qualified-lead alerts).
Validated/clamped by notifications.normalize_notification_settings;
NULL = every toggle at its default (on). JSON so a new toggle never
needs a migration, same pattern as lead_settings.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c3f8a1d6e9b4"
down_revision: Union[str, None] = "b7d6e5f4a3c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("notification_settings", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "notification_settings")

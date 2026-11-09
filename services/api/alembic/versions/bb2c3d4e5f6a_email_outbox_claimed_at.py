"""Track when an email outbox row entered `sending`.

Without a timestamp the worker cannot tell a row that is actively being sent
from one stranded by a crash between the claim commit and the provider result.
The reaper requeues rows older than STALE_SENDING_SECONDS; the per-row Resend
idempotency key makes that replay safe.

Revision ID: bb2c3d4e5f6a
Revises: aa1b2c3d4e5f
Create Date: 2026-11-08
"""
from typing import Sequence, Union

from alembic import op

revision: str = "bb2c3d4e5f6a"
down_revision: Union[str, None] = "aa1b2c3d4e5f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE email_outbox "
        "ADD COLUMN IF NOT EXISTS claimed_at TIMESTAMPTZ"
    )
    # Existing `sending` rows have no claim timestamp. Start their stale
    # window now so they are reaped after the normal interval instead of
    # being ignored forever (or requeued while still in flight).
    op.execute(
        "UPDATE email_outbox SET claimed_at = now() "
        "WHERE status = 'sending' AND claimed_at IS NULL"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE email_outbox DROP COLUMN IF EXISTS claimed_at")

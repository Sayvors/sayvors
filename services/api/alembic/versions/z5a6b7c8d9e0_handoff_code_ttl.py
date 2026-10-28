"""Expiring WhatsApp handoff codes.

Revision ID: z5a6b7c8d9e0
Revises: z4a5b6c7d8e9
Create Date: 2026-10-26

The review reply links to wa.me with the ticket's handoff code in the
`text` payload. That link lives on a public Google listing forever, so the
code must not resolve forever: a customer (or a scraper) finding a two-year-old
reply must not reopen a closed ticket.

- `review_issues.handoff_code_expires_at` — when the code stops resolving.
  NULL keeps legacy rows working: a code minted before this migration had no
  promise of expiry, and silently killing it would strand a customer who is
  mid-conversation. New codes always get a value.
- `auto_reply_configs.handoff_code_ttl_days` — per-channel lifetime, managed
  from the tenant's review settings. Clamped to [1, 30] by the service layer.

Both statements are idempotent (`IF NOT EXISTS`), so a re-run after a partial
deploy is safe. The backfill gives every existing code a fresh window starting
now instead of retroactively expiring codes that are already in customers'
hands.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "z5a6b7c8d9e0"
down_revision: Union[str, None] = "z4a5b6c7d8e9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE review_issues ADD COLUMN IF NOT EXISTS "
        "handoff_code_expires_at TIMESTAMPTZ"
    )
    op.execute(
        "ALTER TABLE auto_reply_configs ADD COLUMN IF NOT EXISTS "
        "handoff_code_ttl_days INTEGER NOT NULL DEFAULT 1"
    )
    # Backfill in two passes: channels with an explicit config use its TTL;
    # channels with no config row get the default. Both passes filter on
    # `handoff_code_expires_at IS NULL`, so a re-run is a no-op.
    op.execute(
        "UPDATE review_issues AS ri "
        "SET handoff_code_expires_at = NOW() + "
        "    (GREATEST(1, LEAST(30, COALESCE(arc.handoff_code_ttl_days, 1))) "
        "     || ' days')::interval "
        "FROM auto_reply_configs AS arc "
        "WHERE arc.channel_id = ri.channel_id "
        "  AND ri.handoff_code IS NOT NULL "
        "  AND ri.handoff_code_expires_at IS NULL"
    )
    op.execute(
        "UPDATE review_issues "
        "SET handoff_code_expires_at = NOW() + INTERVAL '1 day' "
        "WHERE handoff_code IS NOT NULL "
        "  AND handoff_code_expires_at IS NULL"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE auto_reply_configs DROP COLUMN IF EXISTS handoff_code_ttl_days"
    )
    op.execute(
        "ALTER TABLE review_issues DROP COLUMN IF EXISTS handoff_code_expires_at"
    )

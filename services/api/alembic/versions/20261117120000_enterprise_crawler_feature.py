"""Enterprise-only website crawler entitlement.

Adds the ``crawler`` flag explicitly to every plan (so the admin plans page
shows a controllable toggle) and enables it for Enterprise only. Lower tiers
never get it via seed or backfill; an operator can still turn it on manually
for a negotiated deal.

Revision ID: 20261117120000
Revises: 20261117110000
"""
from typing import Sequence, Union

from alembic import op

revision: str = "20261117120000"
down_revision: Union[str, None] = "20261117110000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "UPDATE plans SET features = COALESCE(features, '{}'::jsonb) "
        "|| '{\"crawler\": false}'::jsonb "
        "WHERE NOT (COALESCE(features, '{}'::jsonb) ? 'crawler')"
    )
    op.execute(
        "UPDATE plans SET features = COALESCE(features, '{}'::jsonb) "
        "|| '{\"crawler\": true}'::jsonb WHERE slug = 'enterprise'"
    )


def downgrade() -> None:
    op.execute("UPDATE plans SET features = features - 'crawler'")

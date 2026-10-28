"""plan_baseline_features

Revision ID: h4b5c6d7e8f9
Revises: a9b0c1d2e3f4
Create Date: 2026-10-28 20:00:00.000000

Backfill the enforced baseline features onto every existing plan.

The original plan seed only listed AI/posts/media/reviews. Phase B then
enforced `channels` and `messaging`, so every seeded plan denied them - a
tenant on any plan could not connect a channel or send an inbox message.
This migration adds the two keys only when they are absent, so an admin's
explicit false is never overwritten. Fresh databases get the seed first and
this backfill second.
"""
from typing import Sequence, Union

from alembic import op

revision: str = 'h4b5c6d7e8f9'
down_revision: Union[str, None] = 'a9b0c1d2e3f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE plans
        SET features = COALESCE(features, '{}'::jsonb) || '{"channels": true}'::jsonb
        WHERE NOT (COALESCE(features, '{}'::jsonb) ? 'channels')
        """
    )
    op.execute(
        """
        UPDATE plans
        SET features = COALESCE(features, '{}'::jsonb) || '{"messaging": true}'::jsonb
        WHERE NOT (COALESCE(features, '{}'::jsonb) ? 'messaging')
        """
    )


def downgrade() -> None:
    # Data backfill: leave the keys in place. Removing them would disable the
    # baseline features on every plan, which is the outage this fixes.
    pass

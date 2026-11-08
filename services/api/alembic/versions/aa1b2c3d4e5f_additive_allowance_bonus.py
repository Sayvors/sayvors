"""Make allowance top-ups additive bonuses over the plan limit.

Message and channel top-ups used to be stored as an absolute
`*_limit_override`. Once set, the tenant stopped following its plan: an admin
plan change or a plan-catalog edit did not move the tenant's limit again.

This converts the purchased amount into a bonus that is added to whatever plan
the tenant is on, then clears the absolute override. The override columns are
kept physically for one release so a rolling deploy cannot break an old worker
that still selects them; application code no longer reads or writes them.

Revision ID: aa1b2c3d4e5f
Revises: f3b4c5d6e7a8
Create Date: 2026-11-08
"""
from typing import Sequence, Union

from alembic import op

revision: str = "aa1b2c3d4e5f"
down_revision: Union[str, None] = "f3b4c5d6e7a8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE tenant_subscriptions "
        "ADD COLUMN IF NOT EXISTS message_bonus INTEGER NOT NULL DEFAULT 0"
    )
    op.execute(
        "ALTER TABLE tenant_subscriptions "
        "ADD COLUMN IF NOT EXISTS channels_bonus INTEGER NOT NULL DEFAULT 0"
    )

    # An old override was an absolute limit. The amount the tenant actually
    # bought is whatever it added on top of the plan at grant time. Clamp at
    # zero so an override below the plan never becomes a negative bonus.
    #
    # NULL plan limit means unlimited: there is no base to add to, so the
    # bonus stays 0 and clearing the override leaves the tenant unlimited.
    op.execute(
        """
        UPDATE tenant_subscriptions AS s
        SET message_bonus = GREATEST(
            0,
            s.message_limit_override - COALESCE(p.max_messages_per_month, s.message_limit_override)
        )
        FROM plans AS p
        WHERE s.plan_id = p.id
          AND s.message_limit_override IS NOT NULL
          AND p.max_messages_per_month IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE tenant_subscriptions AS s
        SET channels_bonus = GREATEST(
            0,
            s.channels_limit_override - COALESCE(p.max_channels, s.channels_limit_override)
        )
        FROM plans AS p
        WHERE s.plan_id = p.id
          AND s.channels_limit_override IS NOT NULL
          AND p.max_channels IS NOT NULL
        """
    )
    op.execute(
        "UPDATE tenant_subscriptions "
        "SET message_limit_override = NULL, channels_limit_override = NULL "
        "WHERE message_limit_override IS NOT NULL OR channels_limit_override IS NOT NULL"
    )


def downgrade() -> None:
    # Restore the absolute form so code from before this revision keeps the
    # purchased amount after a rollback.
    op.execute(
        """
        UPDATE tenant_subscriptions AS s
        SET message_limit_override = p.max_messages_per_month + s.message_bonus
        FROM plans AS p
        WHERE s.plan_id = p.id
          AND s.message_bonus > 0
          AND p.max_messages_per_month IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE tenant_subscriptions AS s
        SET channels_limit_override = p.max_channels + s.channels_bonus
        FROM plans AS p
        WHERE s.plan_id = p.id
          AND s.channels_bonus > 0
          AND p.max_channels IS NOT NULL
        """
    )
    op.execute("ALTER TABLE tenant_subscriptions DROP COLUMN IF EXISTS channels_bonus")
    op.execute("ALTER TABLE tenant_subscriptions DROP COLUMN IF EXISTS message_bonus")

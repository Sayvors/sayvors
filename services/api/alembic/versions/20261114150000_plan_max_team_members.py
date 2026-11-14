"""plan max_team_members cap

Revision ID: 20261114150000
Revises: 20261114120000
Create Date: 2026-11-14

§34 item 2 of the readiness report: cap how many people can be invited into a
workspace. The team module is fully built (invites, roles, per-channel access)
but had no member cap, so a Free Trial tenant could invite unlimited people.
Invites are counted as seats too — a pending invite holds the slot until it is
revoked or accepted. Enterprise stays NULL (unlimited).
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20261114150000"
down_revision: Union[str, None] = "20261114120000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE plans ADD COLUMN IF NOT EXISTS max_team_members INTEGER")
    # Seed tier values. Idempotent: only fills rows that have no value yet, so
    # an admin's explicit edit is never overwritten by a re-run.
    op.execute(
        """
        UPDATE plans SET max_team_members = 1
        WHERE slug = 'free-trial' AND max_team_members IS NULL
        """
    )
    op.execute(
        """
        UPDATE plans SET max_team_members = 3
        WHERE slug = 'starter' AND max_team_members IS NULL
        """
    )
    op.execute(
        """
        UPDATE plans SET max_team_members = 10
        WHERE slug = 'pro' AND max_team_members IS NULL
        """
    )
    op.execute(
        """
        UPDATE plans SET max_team_members = 50
        WHERE slug = 'growth' AND max_team_members IS NULL
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE plans DROP COLUMN IF EXISTS max_team_members")

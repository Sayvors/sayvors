"""plan max_locations cap

Revision ID: 20261114120000
Revises: 20261112140000
Create Date: 2026-11-14

§34 of the readiness report: cap how many Google Business Profile locations a
tenant can create/connect. Locations are stored as `google_reviews` channel
rows, and both `POST /api/v1/locations` and the Google OAuth callback create
them directly — neither checked `max_channels`, so a Free Trial tenant could
create unlimited locations. This adds the cap column and seeds the tier
values from the §6b catalog (null = unlimited).
"""

from typing import Sequence, Union

from alembic import op

revision: str = "20261114120000"
down_revision: Union[str, None] = "20261112140000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE plans ADD COLUMN IF NOT EXISTS max_locations INTEGER")
    # Seed tier values. Idempotent: only fills rows that have no value yet, so
    # an admin's explicit edit is never overwritten by a re-run. Enterprise
    # stays NULL (unlimited).
    op.execute(
        """
        UPDATE plans SET max_locations = 1
        WHERE slug IN ('free-trial', 'starter') AND max_locations IS NULL
        """
    )
    op.execute(
        """
        UPDATE plans SET max_locations = 5
        WHERE slug = 'pro' AND max_locations IS NULL
        """
    )
    op.execute(
        """
        UPDATE plans SET max_locations = 25
        WHERE slug = 'growth' AND max_locations IS NULL
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE plans DROP COLUMN IF EXISTS max_locations")

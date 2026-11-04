"""Store the Google verification resource name.

Completing a verification requires the exact resource name Google returned
when the request was created (`locations/{id}/verifications/{verification}`),
not just the method and contact target. The local row keeps it so the
merchant can submit the PIN in a later request.

Revision ID: c8f5a2b3d6e7
Revises: b7e4f1a9c2d8
Create Date: 2026-11-04
"""
from typing import Sequence, Union

from alembic import op

revision: str = "c8f5a2b3d6e7"
down_revision: Union[str, None] = "b7e4f1a9c2d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE channel_verifications "
        "ADD COLUMN IF NOT EXISTS provider_name VARCHAR(255)"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE channel_verifications DROP COLUMN IF EXISTS provider_name"
    )

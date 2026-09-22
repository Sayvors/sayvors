"""Opening date on location_profiles (Google openInfo.openingDate).

Revision ID: z2a3b4c5d6e7
Revises: y1z2a3b4c5d6
Create Date: 2026-09-21

Nullable date — older rows simply have none; the locations UI offers an
"Opening date" field and the native Google path pushes it.
"""
import sqlalchemy as sa

from alembic import op

revision = "z2a3b4c5d6e7"
down_revision = "y1z2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "location_profiles",
        sa.Column("opening_date", sa.Date(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("location_profiles", "opening_date")

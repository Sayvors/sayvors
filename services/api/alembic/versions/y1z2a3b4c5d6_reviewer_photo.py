"""Reviewer profile photo URL on review_insights.

Revision ID: y1z2a3b4c5d6
Revises: x0y1z2a3b4c5
Create Date: 2026-09-21

Stores the reviewer's avatar: Google's reviewer.profilePhotoUrl on the
native path, the upstream photo field on Localith when present. Plain
nullable column — old rows stay NULL and the UI falls back to initials.
"""
import sqlalchemy as sa

from alembic import op

revision = "y1z2a3b4c5d6"
down_revision = "x0y1z2a3b4c5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "review_insights",
        sa.Column("reviewer_photo_url", sa.String(1024), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("review_insights", "reviewer_photo_url")

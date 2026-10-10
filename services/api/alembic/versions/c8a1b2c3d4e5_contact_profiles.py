"""Contact profile cache (names, usernames, avatars).

Revision ID: c8a1b2c3d4e5
Revises: b5a4c3d2e1f0
Create Date: 2026-10-05

One row per (tenant, platform, contact): WhatsApp gives the profile name
free on every webhook; Instagram/Messenger expose name/username/avatar via
a Graph read on the conversation participant. Avatar URLs are temporary
CDN links — profile_fetched_at drives a weekly refresh.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "c8a1b2c3d4e5"
down_revision: Union[str, None] = "b5a4c3d2e1f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "contact_profiles",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("platform", sa.String(length=20), nullable=False),
        sa.Column("contact_id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=True),
        sa.Column("username", sa.String(length=120), nullable=True),
        sa.Column("avatar_url", sa.String(length=1024), nullable=True),
        sa.Column("profile_fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "tenant_id", "platform", "contact_id",
            name="uq_contact_profiles_identity",
        ),
    )
    op.create_index("ix_contact_profiles_tenant_id", "contact_profiles", ["tenant_id"])
    op.create_index("ix_contact_profiles_platform", "contact_profiles", ["platform"])
    op.create_index("ix_contact_profiles_contact_id", "contact_profiles", ["contact_id"])


def downgrade() -> None:
    op.drop_index("ix_contact_profiles_contact_id", table_name="contact_profiles")
    op.drop_index("ix_contact_profiles_platform", table_name="contact_profiles")
    op.drop_index("ix_contact_profiles_tenant_id", table_name="contact_profiles")
    op.drop_table("contact_profiles")

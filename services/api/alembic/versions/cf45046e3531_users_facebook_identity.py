"""users: facebook_id (unique)

Revision ID: cf45046e3531
Revises: c6d7e8f9a0b1
Create Date: 2026-09-24
"""
from alembic import op
import sqlalchemy as sa

revision = "cf45046e3531"
down_revision = "c6d7e8f9a0b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("facebook_id", sa.String(length=64), nullable=True))
    op.create_index(op.f("ix_users_facebook_id"), "users", ["facebook_id"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_users_facebook_id"), table_name="users")
    op.drop_column("users", "facebook_id")

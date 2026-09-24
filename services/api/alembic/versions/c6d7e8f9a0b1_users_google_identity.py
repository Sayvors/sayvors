"""users: google_sub (unique) + avatar_url

Revision ID: c6d7e8f9a0b1
Revises: b5c6d7e8f9a0
Create Date: 2026-09-24
"""
from alembic import op
import sqlalchemy as sa

revision = "c6d7e8f9a0b1"
down_revision = "b5c6d7e8f9a0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("google_sub", sa.String(length=64), nullable=True))
    op.add_column("users", sa.Column("avatar_url", sa.String(length=500), nullable=True))
    op.create_index(op.f("ix_users_google_sub"), "users", ["google_sub"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_users_google_sub"), table_name="users")
    op.drop_column("users", "avatar_url")
    op.drop_column("users", "google_sub")

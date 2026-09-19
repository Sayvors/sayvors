"""add server_defaults for NOT NULL user columns

Revision ID: a1b2c3d4e5f6
Revises: 9528ad5dd83e
Create Date: 2026-08-05 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '9528ad5dd83e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add server_default for NOT NULL columns that were added without one.
    # This prevents ALTER TABLE failure on non-empty users tables.
    op.alter_column('users', 'email_verified', server_default='false')
    op.alter_column('users', 'failed_login_attempts', server_default='0')

    # Backfill existing rows
    op.execute("UPDATE users SET email_verified = false WHERE email_verified IS NULL")
    op.execute("UPDATE users SET failed_login_attempts = 0 WHERE failed_login_attempts IS NULL")


def downgrade() -> None:
    op.alter_column('users', 'failed_login_attempts', server_default=None)
    op.alter_column('users', 'email_verified', server_default=None)

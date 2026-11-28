"""Widen users.plan to match the 40-character plan catalog slug.

Revision ID: 20261128100000
Revises: 20261126144000
"""
from alembic import op

revision = "20261128100000"
down_revision = "20261126144000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE users ALTER COLUMN plan TYPE VARCHAR(40)")


def downgrade() -> None:
    # Existing long slugs would be truncated by Postgres on downgrade. Refuse
    # rather than silently corrupting the canonical plan identifier.
    op.execute(
        "DO $$ BEGIN "
        "IF EXISTS (SELECT 1 FROM users WHERE length(plan) > 16) THEN "
        "RAISE EXCEPTION 'cannot downgrade users.plan while long slugs exist'; "
        "END IF; "
        "END $$"
    )
    op.execute("ALTER TABLE users ALTER COLUMN plan TYPE VARCHAR(16)")

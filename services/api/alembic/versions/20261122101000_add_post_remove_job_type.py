"""Add post.remove job type.

Revision ID: 20261122101000
Revises: 20261122100000
Create Date: 2026-11-22
"""

from alembic import op

revision = "20261122101000"
down_revision = "20261122100000"
branch_labels = None
depends_on = None

JOB_TYPE_ENUM = "job_type"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            f"ALTER TYPE {JOB_TYPE_ENUM} ADD VALUE IF NOT EXISTS 'post.remove'"
        )


def downgrade() -> None:
    # Postgres cannot drop a single enum value safely; leave it in place.
    pass

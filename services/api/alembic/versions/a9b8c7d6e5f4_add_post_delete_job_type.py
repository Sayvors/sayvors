"""Add 'post.delete' to the job_type enum.

Revision ID: a9b8c7d6e5f4
Revises: f1a2b3c4d5e8
Create Date: 2026-10-20

The publish composer can schedule a post's removal (a promotional post
with an end date). The removal is a job of its own on the publishing
lane — `post.delete` — so it rides the same lease, retry and idempotency
machinery as everything else instead of being a cron entry bolted on the
side.

The model gained the value, but Postgres only accepts what the enum
type holds: a job row with job_type='post.delete' fails on a database
that has not been migrated with

  invalid input value for enum job_type: "post.delete"

New enum values cannot be added inside a transaction block, hence the
autocommit block (same pattern as w9x0y1z2a3b4).
"""
from alembic import op

revision = "a9b8c7d6e5f4"
down_revision = "f1a2b3c4d5e8"
branch_labels = None
depends_on = None

JOB_TYPE_ENUM = "job_type"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            f"ALTER TYPE {JOB_TYPE_ENUM} ADD VALUE IF NOT EXISTS 'post.delete'"
        )


def downgrade() -> None:
    # Postgres cannot drop a single enum value; recreating the type would
    # rewrite every row. The value stays — harmless when unused.
    pass

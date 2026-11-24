"""Add missing job types to the job_type enum.

Revision ID: 20261121140000
Revises: 20261121130000
Create Date: 2026-11-21

The Promotion photo check is a job on the realtime lane (publication waits
on it), so the job row needs its own enum value. The model gained the value,
but Postgres only accepts what the enum type holds: a job row with
job_type='media.banner_check' fails with

  invalid input value for enum job_type: "media.banner_check"

on a database that has not been migrated (SQLite tests never see this —
they validate against the model, not the live enum).

The same audit found two pre-existing model values that were never added
to the live enum either: 'review_request.send' and 'rag.ingest' — their
job rows would fail identically. All three are added here.

New enum values cannot be added inside a transaction block, hence the
autocommit block (same pattern as a9b8c7d6e5f4).
"""
from alembic import op

revision = "20261121140000"
down_revision = "20261121130000"
branch_labels = None
depends_on = None

JOB_TYPE_ENUM = "job_type"

MISSING_VALUES = (
    "media.banner_check",
    "review_request.send",
    "rag.ingest",
)


def upgrade() -> None:
    with op.get_context().autocommit_block():
        for value in MISSING_VALUES:
            op.execute(
                f"ALTER TYPE {JOB_TYPE_ENUM} ADD VALUE IF NOT EXISTS '{value}'"
            )


def downgrade() -> None:
    # Postgres cannot drop a single enum value; recreating the type would
    # rewrite every row. The values stay — harmless when unused.
    pass

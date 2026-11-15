"""convert review_problem_issues.status to the real Postgres enum

Revision ID: 20261115010000
Revises: 20261115000000
Create Date: 2026-11-15

The first revision of this table used raw SQL with ``status VARCHAR(20)``,
while the ORM model declares the named enum ``review_problem_issue_status``.
Inserts then fail with ``type "review_problem_issue_status" does not exist``
(observed on staging).

This migration repairs the column in place. The default is dropped and
re-created around the type change because Postgres cannot auto-cast a string
column default to a new enum type. Fresh installs (where create_table already
made the enum) hit the same statements harmlessly.
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "20261115010000"
down_revision: Union[str, None] = "20261115000000"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ENUM_NAME = "review_problem_issue_status"


def upgrade() -> None:
    # 1) Ensure the enum type exists (idempotent).
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = '{_ENUM_NAME}') THEN
                CREATE TYPE {_ENUM_NAME} AS ENUM ('open', 'in_progress', 'done', 'dismissed');
            END IF;
        END
        $$;
        """
    )
    # 2) Drop the column default — a varchar default cannot be cast
    #    automatically to the enum, which is what made the plain ALTER fail.
    op.execute(
        "ALTER TABLE review_problem_issues ALTER COLUMN status DROP DEFAULT"
    )
    # 3) Convert the column, casting each existing value explicitly.
    op.execute(
        f"""
        ALTER TABLE review_problem_issues
        ALTER COLUMN status TYPE {_ENUM_NAME}
        USING status::{_ENUM_NAME};
        """
    )
    # 4) Restore the default (now a real enum literal).
    op.execute(
        f"ALTER TABLE review_problem_issues ALTER COLUMN status SET DEFAULT 'open'::review_problem_issue_status"
    )


def downgrade() -> None:
    op.execute(
        "ALTER TABLE review_problem_issues ALTER COLUMN status DROP DEFAULT"
    )
    op.execute(
        """
        ALTER TABLE review_problem_issues
        ALTER COLUMN status TYPE VARCHAR(20)
        USING status::text;
        """
    )
    op.execute(
        "ALTER TABLE review_problem_issues ALTER COLUMN status SET DEFAULT 'open'"
    )
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_type WHERE typname = '{_ENUM_NAME}') THEN
                DROP TYPE {_ENUM_NAME};
            END IF;
        END
        $$;
        """
    )
    # For the ORM to keep working post-downgrade the model would need to match,
    # which this migration cannot guarantee — downgrade is best-effort.
    _ = sa

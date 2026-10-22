"""Add a hard deadline to jobs.

A job scheduled for later can carry the last moment it may still run
(a scheduled post removal, a promo that expires). The deadline clamps the
schedule - the job becomes due AT the deadline instead of later - and a job
picked up after its deadline is cancelled rather than run late, so a backlog
after an outage cannot turn into a burst of late external calls.

Idempotent: re-running against a database that already has the column is a
no-op.
"""
from alembic import op

revision = "h1a2b3c4d5e6"
down_revision = "f2e3d4c5b6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS hard_deadline_at TIMESTAMP WITH TIME ZONE")
    op.execute("CREATE INDEX IF NOT EXISTS ix_jobs_hard_deadline ON jobs (hard_deadline_at)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_jobs_hard_deadline")
    op.execute("ALTER TABLE jobs DROP COLUMN IF EXISTS hard_deadline_at")

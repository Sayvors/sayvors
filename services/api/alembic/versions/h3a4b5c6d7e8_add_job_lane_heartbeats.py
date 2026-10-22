"""Add the job lane heartbeat table.

One row per lane: which worker is running it and when it was last seen. A
lane that stopped ticking is invisible otherwise - the queue simply stops
moving and nobody notices until a merchant complains. The runner refreshes
its row on every claim; the reaper reports lanes that went quiet.

Idempotent: re-running against a database that already has the table is a
no-op.
"""
import sqlalchemy as sa
from alembic import op

revision = "h3a4b5c6d7e8"
down_revision = "h2a3b4c5d6e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_bind().dialect.has_table("job_lane_heartbeats"):
        return
    op.create_table(
        "job_lane_heartbeats",
        sa.Column("lane", sa.String(length=32), primary_key=True),
        sa.Column("worker_id", sa.String(length=64), nullable=False),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("jobs_claimed", sa.Integer(), nullable=False, server_default="0"),
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_job_lane_heartbeats_last_seen "
        "ON job_lane_heartbeats (last_seen_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_job_lane_heartbeats_last_seen")
    op.drop_table("job_lane_heartbeats")

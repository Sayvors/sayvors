"""Add job_id FK to domain tables for unified job system.

Links stt_jobs, tts_jobs, scrape_jobs, ingest_jobs, location_posts, and
location_media to the unified jobs table. Nullable so existing rows are
not broken; new code populates it.
"""
from alembic import op

revision = "l7m8n9o0p1q2"
down_revision = "k6l7m8n9o0p1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE stt_jobs ADD COLUMN IF NOT EXISTS job_id VARCHAR(36)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_stt_jobs_job_id ON stt_jobs (job_id)")
    op.execute("ALTER TABLE tts_jobs ADD COLUMN IF NOT EXISTS job_id VARCHAR(36)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_tts_jobs_job_id ON tts_jobs (job_id)")
    op.execute("ALTER TABLE scrape_jobs ADD COLUMN IF NOT EXISTS job_id VARCHAR(36)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_scrape_jobs_job_id ON scrape_jobs (job_id)")
    op.execute("ALTER TABLE ingest_jobs ADD COLUMN IF NOT EXISTS job_id VARCHAR(36)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_ingest_jobs_job_id ON ingest_jobs (job_id)")
    op.execute("ALTER TABLE location_posts ADD COLUMN IF NOT EXISTS job_id VARCHAR(36)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_location_posts_job_id ON location_posts (job_id)")
    op.execute("ALTER TABLE location_media ADD COLUMN IF NOT EXISTS job_id VARCHAR(36)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_location_media_job_id ON location_media (job_id)")


def downgrade() -> None:
    for table in ("stt_jobs", "tts_jobs", "scrape_jobs", "ingest_jobs", "location_posts", "location_media"):
        op.execute(f"DROP INDEX IF EXISTS ix_{table}_job_id")
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS job_id")

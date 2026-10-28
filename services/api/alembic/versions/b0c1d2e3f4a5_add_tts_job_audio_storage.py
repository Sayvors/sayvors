"""Store the rendered audio of a TTS job privately.

Revision ID: b0c1d2e3f4a5
Revises: a9b8c7d6e5f4
Create Date: 2026-10-21

The TTS HTTP job used to mark itself completed without rendering anything.
It now renders through the TTS capability and stores the bytes under the
tenant's private docs prefix. The key and mime type live on the row so the
ownership-checked playback route can serve the right container; ``audio_url``
stays as the client-facing path.

The columns are added with IF NOT EXISTS because staging may already carry
them from a previous attempt; re-running this migration must be a no-op.
"""
from alembic import op

revision = "b0c1d2e3f4a5"
down_revision = "a9b8c7d6e5f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE tts_jobs ADD COLUMN IF NOT EXISTS storage_key VARCHAR(500)"
    )
    op.execute(
        "ALTER TABLE tts_jobs ADD COLUMN IF NOT EXISTS audio_mime VARCHAR(64)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE tts_jobs DROP COLUMN IF EXISTS audio_mime")
    op.execute("ALTER TABLE tts_jobs DROP COLUMN IF EXISTS storage_key")

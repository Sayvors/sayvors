"""asr_engine_configs

Admin-managed speech-to-text providers, configured like embeddings: one row
per provider, Fernet-encrypted key, exactly one active engine. With no active
row (or a disabled one) transcription falls back to the local faster-whisper
model, so this migration is additive and safe to apply on any tenant state.

Revision ID: ed44c60beb4c92aa
Revises: 4b8820f95bf2ab91
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "ed44c60beb4c92aa"
down_revision: Union[str, None] = "4b8820f95bf2ab91"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS asr_engine_configs (
            provider VARCHAR(32) PRIMARY KEY,
            model VARCHAR(80),
            key_encrypted TEXT,
            base_url VARCHAR(300),
            languages VARCHAR(200) NOT NULL DEFAULT '*',
            enabled BOOLEAN NOT NULL DEFAULT TRUE,
            active BOOLEAN NOT NULL DEFAULT FALSE,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS asr_engine_configs")

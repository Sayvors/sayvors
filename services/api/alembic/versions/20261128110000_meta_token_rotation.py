"""Add WhatsApp token classification and rotation state.

Revision ID: 20261128110000
Revises: 20261128100000
"""
from alembic import op

revision = "20261128110000"
down_revision = "20261128100000"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE meta_connections ADD COLUMN IF NOT EXISTS token_kind VARCHAR(64)")
    op.execute("ALTER TABLE meta_connections ADD COLUMN IF NOT EXISTS data_access_expires_at TIMESTAMPTZ")
    op.execute("ALTER TABLE meta_connections ADD COLUMN IF NOT EXISTS token_last_rotated_at TIMESTAMPTZ")
    op.execute(
        "ALTER TABLE meta_connections ADD COLUMN IF NOT EXISTS "
        "token_rotation_attempts INTEGER NOT NULL DEFAULT 0"
    )
    op.execute("ALTER TABLE meta_connections ADD COLUMN IF NOT EXISTS token_rotation_error VARCHAR(64)")
    op.execute("ALTER TABLE meta_connections ADD COLUMN IF NOT EXISTS token_rotation_next_attempt_at TIMESTAMPTZ")
    op.execute("ALTER TABLE meta_connections ADD COLUMN IF NOT EXISTS token_rotation_lease_until TIMESTAMPTZ")
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_meta_connections_token_rotation_due "
        "ON meta_connections (provider, status, token_expires_at)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_meta_connections_token_rotation_due")
    op.execute("ALTER TABLE meta_connections DROP COLUMN IF EXISTS token_rotation_lease_until")
    op.execute("ALTER TABLE meta_connections DROP COLUMN IF EXISTS token_rotation_next_attempt_at")
    op.execute("ALTER TABLE meta_connections DROP COLUMN IF EXISTS token_rotation_error")
    op.execute("ALTER TABLE meta_connections DROP COLUMN IF EXISTS token_rotation_attempts")
    op.execute("ALTER TABLE meta_connections DROP COLUMN IF EXISTS token_last_rotated_at")
    op.execute("ALTER TABLE meta_connections DROP COLUMN IF EXISTS data_access_expires_at")
    op.execute("ALTER TABLE meta_connections DROP COLUMN IF EXISTS token_kind")

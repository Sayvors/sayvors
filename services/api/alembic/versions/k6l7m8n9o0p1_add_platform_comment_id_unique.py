"""Add unique index on channel_comments.platform_comment_id.

Enforces the dedupe invariant that the code already assumes: a
platform comment id can only appear once. NULLs are allowed (multiple
NULLs do not collide in Postgres or SQLite).
"""
from alembic import op

revision = "k6l7m8n9o0p1"
down_revision = "j5k6l7m8n9o0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_channel_comments_platform_id "
        "ON channel_comments (platform_comment_id) "
        "WHERE platform_comment_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_channel_comments_platform_id")

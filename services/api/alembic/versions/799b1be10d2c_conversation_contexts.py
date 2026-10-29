"""conversation_contexts table

Stores point-in-time summaries of a conversation: what the customer wants,
what was already promised, what is still open. Written on mode changes, on
resolve and periodically while a thread runs; injected into the AI prompt and
shown as a card in the thread.

``summary`` is encrypted because it paraphrases customer messages — the same
PII as the rows it came from.

Revision ID: 799b1be10d2c
Revises: 6fbcbe8f871b
Create Date: 2026-10-29
"""
import sqlalchemy as sa
from alembic import op

revision = "799b1be10d2c"
down_revision = "6fbcbe8f871b"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conversation_contexts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column(
            "channel_id",
            sa.String(36),
            sa.ForeignKey("channels.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("contact_phone", sa.String(255), nullable=True),
        sa.Column("contact_phone_hash", sa.String(64), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column(
            "message_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "reason", sa.String(32), nullable=False, server_default="manual"
        ),
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    # Latest-context lookup: newest row for one (channel, contact).
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_conversation_contexts_thread "
        "ON conversation_contexts (channel_id, contact_phone_hash, created_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_conversation_contexts_tenant_id "
        "ON conversation_contexts (tenant_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_conversation_contexts_created_at "
        "ON conversation_contexts (created_at)"
    )


def downgrade() -> None:
    op.drop_table("conversation_contexts")

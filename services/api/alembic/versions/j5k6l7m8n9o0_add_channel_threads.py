"""Add channel_threads denormalized inbox summary table.

Replaces the GROUP BY + full-message-load in list_inbox_threads with a
single read from a per-thread summary table. Maintained by SQLAlchemy
event listeners on ChannelMessage, so every insert site updates it
without code changes.
"""
import uuid
from datetime import datetime, timezone

from alembic import op
from sqlalchemy import text

revision = "j5k6l7m8n9o0"
down_revision = "i4j5k6l7m8n9"
branch_labels = None
depends_on = None


def _backfill() -> None:
    """Populate channel_threads from existing channel_messages."""
    conn = op.get_bind()
    groups = conn.execute(text(
        "SELECT channel_id, COALESCE(contact_phone_hash, '__unknown__') as phone_hash, "
        "MAX(contact_phone) as contact_phone, "
        "MAX(created_at) as last_at, "
        "COUNT(*) as total "
        "FROM channel_messages "
        "GROUP BY channel_id, COALESCE(contact_phone_hash, '__unknown__')"
    )).fetchall()

    for g in groups:
        channel_id, phone_hash, contact_phone, last_at, total = g
        last_msg = conn.execute(text(
            "SELECT direction, content, contact_name, category, priority "
            "FROM channel_messages "
            "WHERE channel_id = :cid AND "
            "COALESCE(contact_phone_hash, '__unknown__') = :ph "
            "ORDER BY created_at DESC LIMIT 1"
        ), {"cid": channel_id, "ph": phone_hash}).fetchone()

        if last_msg is None:
            continue

        direction, content, contact_name, category, priority = last_msg

        last_outbound = conn.execute(text(
            "SELECT MAX(created_at) FROM channel_messages "
            "WHERE channel_id = :cid AND "
            "COALESCE(contact_phone_hash, '__unknown__') = :ph "
            "AND direction = 'outbound'"
        ), {"cid": channel_id, "ph": phone_hash}).scalar()

        if phone_hash == "__unknown__":
            unread = 0
        elif last_outbound is None:
            unread = total
        else:
            unread = conn.execute(text(
                "SELECT COUNT(*) FROM channel_messages "
                "WHERE channel_id = :cid AND "
                "COALESCE(contact_phone_hash, '__unknown__') = :ph "
                "AND direction = 'inbound' AND created_at > :lo"
            ), {"cid": channel_id, "ph": phone_hash, "lo": last_outbound}).scalar() or 0

        conn.execute(text(
            "INSERT INTO channel_threads ("
            "id, channel_id, contact_phone, contact_phone_hash, contact_name, "
            "last_message_at, last_direction, last_message_preview, "
            "total_count, unread_count, category, priority, created_at, updated_at"
            ") VALUES ("
            ":id, :cid, :phone, :ph, :name, "
            ":last_at, :direction, :preview, "
            ":total, :unread, :category, :priority, :now, :now"
            ") ON CONFLICT (channel_id, contact_phone_hash) DO NOTHING"
        ), {
            "id": str(uuid.uuid4()),
            "cid": channel_id,
            "phone": None if phone_hash == "__unknown__" else contact_phone,
            "ph": phone_hash,
            "name": contact_name,
            "last_at": last_at,
            "direction": direction,
            "preview": (content or "")[:280],
            "total": total,
            "unread": unread,
            "category": category,
            "priority": priority,
            "now": datetime.now(timezone.utc),
        })


def upgrade() -> None:
    op.execute(
        "CREATE TABLE IF NOT EXISTS channel_threads ("
        "  id VARCHAR(36) PRIMARY KEY,"
        "  channel_id VARCHAR(36) NOT NULL REFERENCES channels(id) ON DELETE CASCADE,"
        "  contact_phone VARCHAR(255),"
        "  contact_phone_hash VARCHAR(64),"
        "  contact_name VARCHAR(120),"
        "  last_message_at TIMESTAMPTZ,"
        "  last_direction VARCHAR(10),"
        "  last_message_preview TEXT,"
        "  total_count INTEGER NOT NULL DEFAULT 0,"
        "  unread_count INTEGER NOT NULL DEFAULT 0,"
        "  category VARCHAR(32),"
        "  priority VARCHAR(16),"
        "  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),"
        "  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()"
        ")"
    )
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_channel_threads_channel_contact "
        "ON channel_threads (channel_id, contact_phone_hash)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_channel_threads_channel_last "
        "ON channel_threads (channel_id, last_message_at)"
    )
    _backfill()


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_channel_threads_channel_last")
    op.execute("DROP INDEX IF EXISTS uq_channel_threads_channel_contact")
    op.execute("DROP TABLE IF EXISTS channel_threads")

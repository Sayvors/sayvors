"""Maintain the denormalized ``channel_threads`` summary table.

Every ``ChannelMessage`` insert updates the corresponding thread row via
SQLAlchemy event listeners, so the 15+ insert sites need no changes. The
inbox reads this table in a single query instead of GROUP BY + full load.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import event, text
from sqlalchemy.engine import Connection

from .models import ChannelMessage

logger = logging.getLogger(__name__)

PREVIEW_LEN = 280


def _upsert_thread(mapper, connection: Connection, target: ChannelMessage) -> None:
    """Upsert the thread summary for ``target``'s (channel, contact)."""
    now = datetime.now(timezone.utc)
    created_at = target.created_at or now
    preview = (target.content or "")[:PREVIEW_LEN]
    is_inbound = target.direction == "inbound"

    # Unread logic: inbound after last outbound resets to 0 on outbound.
    if is_inbound:
        unread_delta = 1
    else:
        unread_delta = None  # signal: reset to 0

    # Use INSERT ... ON CONFLICT (Postgres) with a fallback for SQLite (tests).
    # SQLite supports UPSERT since 3.24 (ON CONFLICT DO UPDATE).
    if unread_delta is None:
        sql = text(
            """
            INSERT INTO channel_threads (
                id, channel_id, contact_phone, contact_phone_hash, contact_name,
                last_message_at, last_direction, last_message_preview,
                total_count, unread_count, category, priority,
                created_at, updated_at
            ) VALUES (
                :id, :channel_id, :contact_phone, :contact_phone_hash, :contact_name,
                :last_at, :direction, :preview,
                1, 0, :category, :priority,
                :now, :now
            )
            ON CONFLICT (channel_id, contact_phone_hash) DO UPDATE SET
                contact_phone = COALESCE(EXCLUDED.contact_phone, channel_threads.contact_phone),
                contact_name = COALESCE(EXCLUDED.contact_name, channel_threads.contact_name),
                last_message_at = CASE
                    WHEN EXCLUDED.last_message_at > channel_threads.last_message_at
                    THEN EXCLUDED.last_message_at ELSE channel_threads.last_message_at END,
                last_direction = CASE
                    WHEN EXCLUDED.last_message_at >= COALESCE(channel_threads.last_message_at, EXCLUDED.last_message_at)
                    THEN EXCLUDED.last_direction ELSE channel_threads.last_direction END,
                last_message_preview = CASE
                    WHEN EXCLUDED.last_message_at >= COALESCE(channel_threads.last_message_at, EXCLUDED.last_message_at)
                    THEN EXCLUDED.last_message_preview ELSE channel_threads.last_message_preview END,
                total_count = channel_threads.total_count + 1,
                unread_count = 0,
                category = COALESCE(EXCLUDED.category, channel_threads.category),
                priority = COALESCE(EXCLUDED.priority, channel_threads.priority),
                updated_at = :now
            """
        )
    else:
        sql = text(
            """
            INSERT INTO channel_threads (
                id, channel_id, contact_phone, contact_phone_hash, contact_name,
                last_message_at, last_direction, last_message_preview,
                total_count, unread_count, category, priority,
                created_at, updated_at
            ) VALUES (
                :id, :channel_id, :contact_phone, :contact_phone_hash, :contact_name,
                :last_at, :direction, :preview,
                1, 1, :category, :priority,
                :now, :now
            )
            ON CONFLICT (channel_id, contact_phone_hash) DO UPDATE SET
                contact_phone = COALESCE(EXCLUDED.contact_phone, channel_threads.contact_phone),
                contact_name = COALESCE(EXCLUDED.contact_name, channel_threads.contact_name),
                last_message_at = CASE
                    WHEN EXCLUDED.last_message_at > channel_threads.last_message_at
                    THEN EXCLUDED.last_message_at ELSE channel_threads.last_message_at END,
                last_direction = CASE
                    WHEN EXCLUDED.last_message_at >= COALESCE(channel_threads.last_message_at, EXCLUDED.last_message_at)
                    THEN EXCLUDED.last_direction ELSE channel_threads.last_direction END,
                last_message_preview = CASE
                    WHEN EXCLUDED.last_message_at >= COALESCE(channel_threads.last_message_at, EXCLUDED.last_message_at)
                    THEN EXCLUDED.last_message_preview ELSE channel_threads.last_message_preview END,
                total_count = channel_threads.total_count + 1,
                unread_count = channel_threads.unread_count + 1,
                category = COALESCE(EXCLUDED.category, channel_threads.category),
                priority = COALESCE(EXCLUDED.priority, channel_threads.priority),
                updated_at = :now
            """
        )

    import uuid

    phone_hash = target.contact_phone_hash or "__unknown__"

    params = {
        "id": str(uuid.uuid4()),
        "channel_id": target.channel_id,
        "contact_phone": target.contact_phone,
        "contact_phone_hash": phone_hash,
        "contact_name": target.contact_name,
        "last_at": created_at,
        "direction": target.direction,
        "preview": preview,
        "category": target.category,
        "priority": target.priority,
        "now": now,
    }
    try:
        connection.execute(sql, params)
    except Exception as exc:
        logger.warning("thread maintenance failed for %s: %s", target.id, exc)


def register_listeners() -> None:
    """Register event listeners. Call once at app startup."""
    event.listen(ChannelMessage, "after_insert", _upsert_thread, propagate=True)


# Register on import so any process that imports channels.models gets it.
try:
    event.listen(ChannelMessage, "after_insert", _upsert_thread, propagate=True)
except Exception:
    pass

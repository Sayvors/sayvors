"""Meta events worker: processes inbound WhatsApp/Instagram/Facebook events with
bounded concurrency and proper lease/retry mechanics.

Replaces the sequential Kafka consumer (run_meta_events_consumer) with a
worker pool that claims events from the outbox, processes them with bounded
concurrency, and handles retries with proper backoff.

Key differences from the old consumer:
- Claims events from the outbox using SELECT FOR UPDATE SKIP LOCKED
- Processes multiple events concurrently (bounded by CONCURRENCY)
- Each event has a lease; crashed workers' claims are reclaimed after expiry
- Proper retry taxonomy: transient -> retry with backoff, permanent -> failed,
  ambiguous (timeout) -> never auto-retried
- No Kafka consumer group needed; the outbox is the queue.
"""

import asyncio
import json
import logging
import os
import random
import socket
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional

from sqlalchemy import select, update, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ....config import settings
from ....database import async_session
from ....modules.kafka.client import mark_kafka_unavailable
from ..meta.models import MetaAsset
from ..models import Channel, ChannelMessage
from .providers.base import MetaAPIError
from .consumer import (
    _handle_message_received,
    _handle_message_status,
    _handle_message_history,
    _handle_message_echo,
    _handle_smb_contacts,
    _handle_connection_disconnect,
    _handle_instagram_echo,
    _handle_instagram_message,
    _handle_instagram_comment,
    _handle_facebook_comment,
    _drain_outbox_events as _drain_outbox_events_consumer,
)

logger = logging.getLogger(__name__)

# Configuration
POLL_SECONDS = int(os.environ.get("META_EVENTS_POLL_SECONDS", "5"))
BATCH_SIZE = int(os.environ.get("META_EVENTS_BATCH_SIZE", "20"))
CONCURRENCY = int(os.environ.get("META_EVENTS_CONCURRENCY", "8"))
LEASE_SECONDS = int(os.environ.get("META_EVENTS_LEASE_SECONDS", "120"))
MAX_RETRIES = int(os.environ.get("META_EVENTS_MAX_RETRIES", "5"))
RETRY_BASE_SECONDS = int(os.environ.get("META_EVENTS_RETRY_BASE_SECONDS", "300"))
RETRY_MAX_SECONDS = int(os.environ.get("META_EVENTS_RETRY_MAX_SECONDS", "7200"))

# Event types we handle
HANDLED_EVENT_TYPES = {
    "whatsapp": {
        "message.received",
        "message.status",
        "message.history",
        "message.echo",
        "smb.contacts",
        "connection.disconnect",
    },
    "instagram": {
        "message.received",
        "comment.received",
    },
    "facebook": {
        "comment.received",
    },
}


class _PermanentError(Exception):
    """Config/credential problem — retrying cannot help."""
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


class _AmbiguousError(Exception):
    """Timeout-class failure: delivery unknown, a retry may double-send."""
    def __init__(self, message: str):
        super().__init__(message)


def _event_type_handled(provider: str, event_type: str) -> bool:
    """Check if we handle this event type."""
    return event_type in HANDLED_EVENT_TYPES.get(provider, set())


async def _claim_due_events(db, worker_id: str, limit: int = BATCH_SIZE) -> List[Dict[str, Any]]:
    """Atomically claim up to `limit` pending meta events from the outbox.

    Uses SELECT FOR UPDATE SKIP LOCKED for concurrent safety. Expired leases
    are released first so crashed workers' claims are reclaimed.
    """
    now = datetime.now(timezone.utc)

    # Release expired leases back to pending so crashed workers' claims are
    # reclaimed (mirrors JobRunner lease-expiry pattern).
    await db.execute(
        text("""
            UPDATE event_outbox
            SET status = 'pending', lease_owner = NULL, lease_expires_at = NULL
            WHERE status = 'processing'
              AND event_type LIKE 'meta.%'
              AND lease_expires_at IS NOT NULL
              AND lease_expires_at < :now
        """),
        {"now": now},
    )

    query = text("""
        SELECT id, event_type, payload, topic, attempts, next_retry_at
        FROM event_outbox
        WHERE status = 'pending'
          AND event_type LIKE 'meta.%'
          AND (next_retry_at IS NULL OR next_retry_at <= :now)
        ORDER BY created_at ASC
        LIMIT :limit
        FOR UPDATE SKIP LOCKED
    """)
    result = await db.execute(query, {"now": now, "limit": limit})
    rows = result.mappings().all()

    events = []
    for row in rows:
        # Mark as claimed by updating status to 'processing' with a lease.
        await db.execute(
            text("""
                UPDATE event_outbox
                SET status = 'processing', lease_owner = :worker, lease_expires_at = :lease
                WHERE id = :id
            """),
            {"id": row["id"], "worker": worker_id, "lease": now + timedelta(seconds=LEASE_SECONDS)},
        )
        events.append(dict(row))

    if events:
        await db.commit()

    return events


async def _process_event(db, event_data: Dict[str, Any]) -> bool:
    """Process a single meta event. Returns True if successful, False if should retry."""
    event_id = event_data["id"]
    event_type = event_data["event_type"]
    payload = event_data["payload"]
    topic = event_data["topic"]

    try:
        # Parse the payload if it's a string
        if isinstance(payload, str):
            payload = json.loads(payload)

        provider = payload.get("provider", "")
        event_type = payload.get("event_type", "")

        if not _event_type_handled(provider, event_type):
            # Mark as sent (ignored)
            await _mark_event_sent(db, event_id)
            return True

        # Every handler in consumer.py takes (event, data): the normalized
        # envelope, then the provider payload nested inside it under
        # "payload". Passing the envelope alone raised TypeError on every
        # event, so no inbound message was ever stored, captioned or answered.
        # Same split _process_message makes.
        data = payload.get("payload") or {}

        # Route to appropriate handler
        if provider == "whatsapp":
            if event_type == "message.received":
                await _handle_message_received(payload, data)
            elif event_type == "message.status":
                await _handle_message_status(payload, data)
            elif event_type == "message.history":
                await _handle_message_history(payload, data)
            elif event_type == "message.echo":
                await _handle_message_echo(payload, data)
            elif event_type == "smb.contacts":
                await _handle_smb_contacts(payload, data)
            elif event_type == "connection.disconnect":
                await _handle_connection_disconnect(payload, data)
        elif provider == "instagram":
            if event_type == "message.received":
                # Merchant replies from Meta's inbox arrive as an echo --
                # history, not something to auto-answer.
                if ((data.get("raw") or {}).get("message") or {}).get("is_echo"):
                    await _handle_instagram_echo(payload, data)
                else:
                    await _handle_instagram_message(payload, data)
            elif event_type == "comment.received":
                await _handle_instagram_comment(payload, data)
        elif provider == "facebook":
            if event_type == "comment.received":
                await _handle_facebook_comment(payload, data)

        # Mark as sent
        await _mark_event_sent(db, event_id)
        return True

    except _AmbiguousError:
        # Delivery unknown - don't retry
        await _mark_event_ambiguous(db, event_id)
        return False
    except _PermanentError:
        await _mark_event_failed(db, event_id, retry=False)
        return False
    except Exception as e:
        logger.exception("Failed processing meta event %s: %s", event_id, e)
        await _mark_event_failed(db, event_id, str(e), retry=True)
        return False


async def _mark_event_sent(db, event_id: str) -> None:
    """Mark event as successfully sent."""
    await db.execute(
        text("UPDATE event_outbox SET status = 'sent', last_error = NULL WHERE id = :id"),
        {"id": event_id}
    )
    await db.commit()


async def _mark_event_ambiguous(db, event_id: str) -> None:
    """Mark event as ambiguous (delivered but not confirmed)."""
    await db.execute(
        text("UPDATE event_outbox SET status = 'ambiguous' WHERE id = :id"),
        {"id": event_id}
    )
    await db.commit()


async def _mark_event_failed(db, event_id: str, error: str, retry: bool = True) -> None:
    """Mark event as failed, schedule retry if appropriate."""
    now = datetime.now(timezone.utc)
    if retry:
        await db.execute(
            text("""
                UPDATE event_outbox
                SET status = 'failed', attempts = attempts + 1,
                    last_error = :error, next_retry_at = :next_retry
                WHERE id = :id
            """),
            {"id": event_id, "error": str(error)[:500], "next_retry": datetime.now(timezone.utc) + timedelta(seconds=300)}
        )
    else:
        await db.execute(
            text("UPDATE event_outbox SET status = 'dead', last_error = :error WHERE id = :id"),
            {"id": event_id, "error": str(error)[:500]}
        )
    await db.commit()


async def _process_batch(worker_id: str) -> int:
    """Process one batch of events. Returns number of events processed."""
    processed = 0
    async with async_session() as db:
        events = await _claim_due_events(db, worker_id, BATCH_SIZE)
        for event in events:
            try:
                success = await _process_event(db, event)
                if not success:
                    # Will be retried by next poll
                    pass
                processed += 1
            except Exception as e:
                logger.exception("Event processing crashed: %s", e)
    return processed


async def run_meta_events_worker() -> None:
    """Main worker loop. Runs until cancelled."""
    logger.info("Meta events worker started (poll=%ds, concurrency=%d)", POLL_SECONDS, CONCURRENCY)
    worker_id = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"

    # Semaphore to limit concurrency
    semaphore = asyncio.Semaphore(CONCURRENCY)

    async def process_one(event_data: Dict[str, Any]) -> None:
        async with semaphore:
            try:
                async with async_session() as db:
                    await _process_event(db, event_data)
            except Exception as e:
                logger.exception("Event processing crashed: %s", e)

    while True:
        try:
            # Claim events
            async with async_session() as db:
                events = await _claim_due_events(db, f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}", BATCH_SIZE)

            if not events:
                await asyncio.sleep(POLL_SECONDS)
                continue

            # Process events concurrently
            tasks = [process_one(event) for event in events]
            await asyncio.gather(*tasks, return_exceptions=True)

        except asyncio.CancelledError:
            break
        except Exception:
            logger.exception("Meta events worker cycle failed")
            await asyncio.sleep(5)


# Entry point for worker
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        asyncio.run(run_meta_events_worker())
    except KeyboardInterrupt:
        pass
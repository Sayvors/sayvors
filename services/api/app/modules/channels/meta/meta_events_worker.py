"""Meta events worker: Kafka consumer for inbound Meta events.

The webhook writes the normalized envelope to the transactional outbox in the
same DB transaction as the raw ledger row. The outbox relay publishes those
rows to `meta-events`; this worker consumes them from Kafka and hands each
envelope to the same handlers the rest of the pipeline uses.

Kafka is the streaming path. Postgres is the durable source and the retry
ledger; it does not transport events more than one hop.

Delivery rules:
- one message per poll keeps offsets ordered per partition
- offsets are committed after the DB outcome is durable
- handler failures mark the outbox row failed and let the relay republish it
  after its backoff interval (handlers are idempotent by message id)
- ambiguous sends stay ambiguous: never retried, so a retry cannot double-send

Scale rule: run one or more replicas; Kafka's consumer group balances the 12
partitions across them. Messages are not independently counted by the relay
because the relay is not the consumer.
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, Any

from sqlalchemy import select, update, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from ....config import settings
from ....database import async_session
from ....modules.kafka.client import mark_kafka_unavailable
from ..meta.models import MetaAsset, MetaWebhookEvent
from ..models import Channel, ChannelMessage
from .providers.base import (
    MetaAmbiguousError as _AmbiguousError,
    MetaPermanentError as _PermanentError,
    MetaAPIError,
)
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
)
from .webhooks.parser import is_message_status_event

logger = logging.getLogger(__name__)

# Configuration
MAX_RETRIES = 10
RETRY_BASE_SECONDS = int(os.environ.get("META_EVENTS_RETRY_BASE_SECONDS", "300"))
RETRY_MAX_SECONDS = int(os.environ.get("META_EVENTS_RETRY_MAX_SECONDS", "7200"))

# The outbox relay publishes to this topic; this consumer owns the queue.
TOPIC = "meta-events"
GROUP_ID = "meta-events-replier"

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


# _PermanentError / _AmbiguousError used to be defined here. They now live in
# providers.base (MetaPermanentError / MetaAmbiguousError) so the consumer can
# raise the exact classes this worker catches — a send that times out mid-
# flight must reach the ambiguous branch, not the generic retry. The old
# names stay importable for the tests and any other callers.
def _event_type_handled(provider: str, event_type: str) -> bool:
    """Check if we handle this event type."""
    if event_type in HANDLED_EVENT_TYPES.get(provider, set()):
        return True
    # Status types carry the status suffix; keep accepting the bare type for
    # events queued before the per-status identity landed.
    return provider == "whatsapp" and is_message_status_event(event_type)


async def _process_event(db, event_data: Dict[str, Any]) -> bool:
    """Process a single meta event. Returns True if successful, False if should retry."""
    event_id = event_data["id"]
    event_type = event_data["event_type"]
    payload = event_data["payload"]
    topic = event_data["topic"]
    webhook_event_id: str | None = None

    try:
        # Parse the payload if it's a string
        if isinstance(payload, str):
            payload = json.loads(payload)

        provider = payload.get("provider", "")
        event_type = payload.get("event_type", "")
        webhook_event_id = payload.get("webhook_event_id")

        if not _event_type_handled(provider, event_type):
            # Mark as sent (ignored)
            await _mark_event_sent(db, event_id, webhook_event_id)
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
            elif is_message_status_event(event_type):
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
        await _mark_event_sent(db, event_id, webhook_event_id)
        return True

    except _AmbiguousError:
        # Delivery unknown - don't retry
        await _mark_event_ambiguous(db, event_id, webhook_event_id)
        return False
    except _PermanentError as e:
        await _mark_event_failed(
            db, event_id, str(e), retry=False,
            webhook_event_id=webhook_event_id,
        )
        return False
    except Exception as e:
        logger.exception("Failed processing meta event %s: %s", event_id, e)
        await _mark_event_failed(
            db, event_id, str(e), retry=True,
            webhook_event_id=webhook_event_id,
        )
        return False


async def _mark_webhook_event(
    db, webhook_event_id: str | None, status: str, error: str | None = None
) -> None:
    """Close the raw webhook row that produced this outbox event.

    Best-effort on purpose: a failure here must never reopen the outbox event
    (the customer may already have the reply). The row keeps a non-terminal
    status and the short orphan window retires it.
    """
    if not webhook_event_id:
        return
    try:
        # ORM update rather than raw SQL: `status` is a Postgres enum, and
        # letting SQLAlchemy bind it keeps the type cast correct everywhere.
        await db.execute(
            update(MetaWebhookEvent)
            .where(
                MetaWebhookEvent.id == webhook_event_id,
                MetaWebhookEvent.status.in_(["received", "unresolved"]),
            )
            .values(
                status=status,
                error=error[:500] if error else None,
            )
        )
        await db.commit()
    except Exception as exc:  # noqa: BLE001 - retention bookkeeping only
        logger.warning(
            "Could not close webhook event %s as %s: %s: %s",
            webhook_event_id, status, type(exc).__name__, str(exc)[:200],
        )
        await db.rollback()


async def _mark_event_sent(
    db, event_id: str, webhook_event_id: str | None = None
) -> None:
    """Mark event as successfully sent."""
    await db.execute(
        text("UPDATE event_outbox SET status = 'sent', last_error = NULL, lease_owner = NULL, lease_expires_at = NULL WHERE id = :id"),
        {"id": event_id}
    )
    await db.commit()
    await _mark_webhook_event(db, webhook_event_id, "processed")


async def _mark_event_ambiguous(
    db, event_id: str, webhook_event_id: str | None = None
) -> None:
    """Mark event as ambiguous (delivered but not confirmed)."""
    await db.execute(
        text("UPDATE event_outbox SET status = 'ambiguous', lease_owner = NULL, lease_expires_at = NULL WHERE id = :id"),
        {"id": event_id}
    )
    await db.commit()
    # Ambiguous is terminal for this worker (a retry could double-send), but
    # the outcome is genuinely unknown — keep the row out of "processed" and
    # let the short orphan window retire it.
    await _mark_webhook_event(
        db, webhook_event_id, "unresolved",
        "delivery outcome ambiguous; not retried",
    )


async def _mark_event_failed(
    db,
    event_id: str,
    error: str,
    retry: bool = True,
    webhook_event_id: str | None = None,
) -> None:
    """Mark event as failed, schedule retry with exponential backoff.

    Retries use exponential backoff (RETRY_BASE_SECONDS ** attempts, capped at
    RETRY_MAX_SECONDS). After MAX_RETRIES attempts the event is marked dead.
    """
    # Check current attempt count to decide dead vs retry.
    result = await db.execute(
        text("SELECT attempts FROM event_outbox WHERE id = :id"),
        {"id": event_id},
    )
    row = result.fetchone()
    attempts = (row[0] if row else 0) + 1

    if retry and attempts < MAX_RETRIES:
        backoff = min(RETRY_BASE_SECONDS * (2 ** (attempts - 1)), RETRY_MAX_SECONDS)
        await db.execute(
            text("""
                UPDATE event_outbox
                SET status = 'failed', attempts = :attempts,
                    last_error = :error, next_retry_at = :next_retry,
                    lease_owner = NULL, lease_expires_at = NULL
                WHERE id = :id
            """),
            {"id": event_id, "error": str(error)[:500],
             "next_retry": datetime.now(timezone.utc) + timedelta(seconds=backoff),
             "attempts": attempts},
        )
        await db.commit()
        # Still retrying: the raw row must remain readable for the retry.
        return

    await db.execute(
        text("UPDATE event_outbox SET status = 'dead', attempts = :attempts, last_error = :error, lease_owner = NULL, lease_expires_at = NULL WHERE id = :id"),
        {"id": event_id, "error": str(error)[:500], "attempts": attempts},
    )
    await db.commit()
    await _mark_webhook_event(db, webhook_event_id, "rejected", str(error))


def _decode_message(value):
    """Normalize kafka bytes/strings/parsed values into one envelope."""
    if isinstance(value, dict):
        return value
    if not isinstance(value, (bytes, bytearray, str)):
        return None
    try:
        decoded = json.loads(
            value.decode("utf-8") if isinstance(value, (bytes, bytearray)) else value
        )
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return decoded if isinstance(decoded, dict) else None


async def run_meta_events_worker() -> None:
    """Consume the meta events stream until cancelled."""
    from ...kafka import client as kafka_client

    if not kafka_client.is_kafka_available(GROUP_ID):
        logger.info("Kafka producer offline; meta events remain buffered in the outbox")

    logger.info("Meta events Kafka consumer started (topic=%s, group=%s)", TOPIC, GROUP_ID)
    while True:
        consumer = None
        try:
            if not kafka_client.is_kafka_available(GROUP_ID):
                await asyncio.sleep(5)
                continue

            consumer = await kafka_client.create_consumer(
                GROUP_ID,
                [TOPIC],
                max_poll_records=1,
            )
            logger.info("Meta events consumer listening on %s", TOPIC)
            async for msg in consumer:
                envelope = _decode_message(msg.value)
                if envelope is None:
                    logger.warning(
                        "Discarding malformed %s payload at offset=%s",
                        TOPIC,
                        msg.offset,
                    )
                    await consumer.commit()
                    continue

                event_id = envelope.get("event_id")
                payload = envelope.get("payload")
                event_type = envelope.get("event_type")
                if not isinstance(event_id, str) or not isinstance(event_type, str) or not isinstance(payload, dict):
                    logger.warning(
                        "Discarding malformed %s envelope at offset=%s",
                        TOPIC,
                        msg.offset,
                    )
                    await consumer.commit()
                    continue

                event_data = {
                    "id": event_id,
                    "event_type": event_type,
                    "topic": msg.topic,
                    "attempts": 0,
                    "next_retry_at": None,
                    "payload": payload,
                }
                async with async_session() as db:
                    await _process_event(db, event_data)
                # The DB outcome is durable here. Handler failures are already
                # staged on the outbox row for backed-off republish; committing
                # stops Kafka from hot-looping the same failure.
                await consumer.commit()
        except asyncio.CancelledError:
            if consumer is not None:
                await consumer.stop()
            raise
        except Exception:
            logger.exception(
                "Meta events Kafka consumer failed — re-creating the consumer"
            )
            kafka_client.mark_kafka_unavailable(GROUP_ID)
            if consumer is not None:
                try:
                    await consumer.stop()
                except Exception:
                    pass
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
"""Meta events ride the outbox -> Kafka relay, as a two-phase handoff.

The outbox is the durable boundary (accepted by the webhook, surviving a
Kafka outage). Kafka is the streaming bus. This file pins the contract that
prevents the two stages from racing each other into a silent drop:

1. The relay claims meta.* rows, publishes them to ``meta-events`` and
   marks them ``published`` — never ``sent``. Kafka returns before the
   consumer has processed them.
2. The consumer closes the business outcome (``sent`` / ``failed`` /
   ``dead`` / ``ambiguous``) against the outbox row.
3. The publish -> CAS must not overwrite a consumer transition: a row whose
   attempt counter moved after the relay claimed it is left alone.
"""
import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.modules.outbox import service as outbox_service
from app.modules.outbox.models import EventOutbox


@pytest_asyncio.fixture
async def outbox_db(db, monkeypatch):
    """Point the publisher's private session at the test database."""
    factory = async_sessionmaker(db.bind, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(outbox_service, "async_session", factory)
    yield db


def _row(
    event_id: str,
    event_type: str,
    topic: str,
    *,
    status="pending",
    attempts=0,
    next_retry_at: datetime | None = None,
) -> EventOutbox:
    return EventOutbox(
        id=event_id,
        event_type=event_type,
        payload={"provider": "whatsapp", "event_type": "message.received"},
        topic=topic,
        status=status,
        attempts=attempts,
        next_retry_at=next_retry_at or datetime.now(timezone.utc),
    )


@pytest.mark.asyncio
async def test_kafka_relay_fetches_meta_events(outbox_db):
    outbox_db.add_all([
        _row(f"meta-{uuid.uuid4().hex[:8]}", "meta.message.received", "meta-events"),
        _row(f"meta-{uuid.uuid4().hex[:8]}", "meta.message.status", "meta-events"),
        _row(f"other-{uuid.uuid4().hex[:8]}", "review.enriched", "review-events"),
    ])
    await outbox_db.commit()

    fetched = await outbox_service.fetch_pending_events(batch_size=100)

    assert {e.event_type for e in fetched} == {
        "meta.message.received",
        "meta.message.status",
        "review.enriched",
    }


@pytest.mark.asyncio
async def test_relay_published_marker_never_overwrites_consumer_progress(outbox_db):
    """Kafka returns before processing; the relay must not revert the row."""
    event = _row(
        f"meta-{uuid.uuid4().hex[:8]}",
        "meta.message.received",
        "meta-events",
        attempts=2,
    )
    outbox_db.add(event)
    await outbox_db.commit()

    claimed = await outbox_service.fetch_pending_events(batch_size=100)
    assert len(claimed) == 1

    # Consumer closes the message first (the relay had already claimed it).
    stored = (await outbox_db.execute(
        select(EventOutbox).where(EventOutbox.id == event.id)
    )).scalar_one()
    stored.status = "sent"
    await outbox_db.commit()

    await outbox_service.mark_published(claimed)

    stored = (await outbox_db.execute(
        select(EventOutbox).where(EventOutbox.id == event.id)
    )).scalar_one()
    assert stored.status == "sent", "relay must not overwrite a consumed event"


@pytest.mark.asyncio
async def test_relay_published_marker_keeps_consumer_retry_backoff(outbox_db):
    """A retry scheduled by the consumer outranks the relay's marker."""
    event = _row(
        f"meta-{uuid.uuid4().hex[:8]}",
        "meta.message.received",
        "meta-events",
        status="failed",
        attempts=2,
    )
    outbox_db.add(event)
    await outbox_db.commit()

    claimed = await outbox_service.fetch_pending_events(batch_size=100)
    assert len(claimed) == 1

    stored = (await outbox_db.execute(
        select(EventOutbox).where(EventOutbox.id == event.id)
    )).scalar_one()
    stored.attempts = 3
    stored.status = "failed"
    stored.next_retry_at = datetime.now(timezone.utc)
    await outbox_db.commit()

    await outbox_service.mark_published(claimed)

    stored = (await outbox_db.execute(
        select(EventOutbox).where(EventOutbox.id == event.id)
    )).scalar_one()
    assert stored.attempts == 3
    assert stored.status == "failed"


@pytest.mark.asyncio
async def test_unhandled_meta_types_are_published_then_marked_sent(outbox_db):
    """Unknown handled set is still a decision, not a silent drop."""
    from app.modules.channels.meta import meta_events_worker as worker

    event = _row(
        f"meta-{uuid.uuid4().hex[:8]}", "meta.something.unknown", "meta-events"
    )
    event_id = event.id
    outbox_db.add(event)
    await outbox_db.commit()

    fetched = await outbox_service.fetch_pending_events(batch_size=100)
    assert [e.id for e in fetched] == [event_id]

    row = {
        "id": event_id,
        "event_type": "meta.something.unknown",
        "topic": "meta-events",
        "attempts": 0,
        "next_retry_at": None,
        "payload": {
            "provider": "whatsapp",
            "event_type": "something.unknown",
            "payload": {"from": "9665", "text": "hi"},
        },
    }
    assert await worker._process_event(outbox_db, row) is True

    outbox_db.expire_all()
    stored = (await outbox_db.execute(
        select(EventOutbox).where(EventOutbox.id == event_id)
    )).scalar_one()
    assert stored.status == "sent"


@pytest.mark.asyncio
async def test_meta_rows_are_marked_published_not_sent(monkeypatch):
    """Publishing to Kafka is not processing; the two statuses stay separate."""
    from app.modules.outbox import worker as relay_worker

    sent = []
    published = []
    producer_sent = []

    class _Producer:
        async def send(self, topic, *, key, value):
            producer_sent.append((topic, key, value))

    async def _get_producer():
        return _Producer()

    async def _mark_published(event_list):
        published.extend(e.id for e in event_list)

    async def _mark_sent(event_ids):
        sent.extend(event_ids)

    monkeypatch.setattr("app.modules.kafka.client.get_kafka_producer", _get_producer)
    monkeypatch.setattr(outbox_service, "mark_published", _mark_published)
    monkeypatch.setattr(outbox_service, "mark_sent", _mark_sent)

    events = [
        _row("meta-1", "meta.message.received", "meta-events"),
        _row("meta-2", "meta.something.unknown", "meta-events"),
    ]

    await relay_worker.OutboxWorker()._send_batch("meta-events", events)

    assert published == ["meta-1", "meta-2"]
    assert sent == []
    assert len(producer_sent) == 2


@pytest.mark.asyncio
async def test_other_rows_keep_sent_semantics(monkeypatch):
    """Non-Kafka-processed lanes keep their existing terminal marker."""
    from app.modules.outbox import worker as relay_worker

    sent = []
    published = []

    class _Producer:
        async def send(self, _topic, *, key, value):
            return None

    async def _get_producer():
        return _Producer()

    async def _mark_published(event_list):
        published.extend(e.id for e in event_list)

    async def _mark_sent(event_ids):
        sent.extend(event_ids)

    monkeypatch.setattr("app.modules.kafka.client.get_kafka_producer", _get_producer)
    monkeypatch.setattr(outbox_service, "mark_published", _mark_published)
    monkeypatch.setattr(outbox_service, "mark_sent", _mark_sent)

    await relay_worker.OutboxWorker()._send_batch(
        "review-events", [_row("review-1", "review.enriched", "review-events")]
    )

    assert sent == ["review-1"]
    assert published == []


@pytest.mark.asyncio
async def test_permanent_meta_errors_fail_fast_without_retry(db):
    """A _PermanentError must not be retried and must keep its message.

    It used to call _mark_event_failed(db, id, retry=False), which bound
    retry=False into the *error* parameter and retried anyway with the text
    "False" — a config problem looked like five transient failures.
    """
    from app.modules.channels.meta import meta_events_worker as worker

    row_id = f"meta-{uuid.uuid4().hex[:8]}"
    db.add(_row(row_id, "meta.message.received", "meta-events"))
    await db.commit()

    async def _boom(payload, data):
        raise worker._PermanentError("no usable access token")

    orig = worker._handle_message_received
    worker._handle_message_received = _boom
    try:
        row = {"id": row_id, "event_type": "meta.message.received",
               "topic": "meta-events", "attempts": 0, "next_retry_at": None,
               "payload": {
                   "provider": "whatsapp", "event_type": "message.received",
                   "payload": {"from": "9665", "text": "hi"},
               }}
        assert await worker._process_event(db, row) is False
    finally:
        worker._handle_message_received = orig

    stored = (await db.execute(
        select(EventOutbox).where(EventOutbox.id == row_id)
    )).scalar_one()
    assert stored.status == "dead", "permanent errors fail fast, not after 5 retries"
    assert "no usable access token" in (stored.last_error or "")

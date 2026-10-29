"""The outbox Kafka publisher must never touch meta.* rows.

Regression guard for a silent message-loss race on staging: the webhook
accepts an inbound (200), writes a pending outbox row, and then two writers
race for it — the outbox→Kafka drainer (3s poll) and the meta events worker
(5s poll). When the drainer won, the row was published to the ``meta-events``
Kafka topic (which nothing consumes since the sequential Kafka consumer was
retired) and marked ``sent``. The meta worker only claims pending/failed rows,
so the event was processed by nobody: no message stored, no AI reply, no log.
Four consecutive customer messages vanished this way while every healthcheck
stayed green.

Ownership is now explicit: ``fetch_pending_events`` excludes ``meta.*`` and
the meta worker owns those rows end to end.
"""
import uuid

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


def _row(event_id: str, event_type: str, topic: str) -> EventOutbox:
    return EventOutbox(
        id=event_id,
        event_type=event_type,
        payload={"provider": "whatsapp", "event_type": "message.received"},
        topic=topic,
        status="pending",
    )


@pytest.mark.asyncio
async def test_kafka_publisher_skips_meta_events(outbox_db):
    outbox_db.add_all([
        _row(f"meta-{uuid.uuid4().hex[:8]}", "meta.message.received", "meta-events"),
        _row(f"meta-{uuid.uuid4().hex[:8]}", "meta.message.status", "meta-events"),
        _row(f"other-{uuid.uuid4().hex[:8]}", "review.enriched", "review-events"),
    ])
    await outbox_db.commit()

    fetched = await outbox_service.fetch_pending_events(batch_size=100)

    assert {e.event_type for e in fetched} == {"review.enriched"}
    still_pending = (await outbox_db.execute(
        select(EventOutbox).where(EventOutbox.event_type.like("meta.%"))
    )).scalars().all()
    assert all(e.status == "pending" for e in still_pending), (
        "meta rows stay pending so the meta worker — their only reader — "
        "can still claim them"
    )


@pytest.mark.asyncio
async def test_unhandled_meta_types_are_still_excluded(outbox_db):
    """The exclusion is on the ``meta.%`` prefix, not the handled set.

    An event type the meta worker does not route is still a meta row: the
    worker marks it sent-after-ignoring, which is a decision. Publishing it to
    Kafka and marking it sent would lose it with no decision at all.
    """
    outbox_db.add(_row(
        f"meta-{uuid.uuid4().hex[:8]}", "meta.something.unknown", "meta-events"
    ))
    await outbox_db.commit()

    assert await outbox_service.fetch_pending_events(batch_size=100) == []


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

"""Email outbox: dedupe, suppression, retries, events and unsubscribe."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.modules.email import outbox
from app.modules.email.models import EmailEvent, EmailOutbox, EmailSuppression
from app.modules.users.models import User

pytestmark = pytest.mark.asyncio


async def _enqueue(db, to="person@example.com", key="welcome:person@example.com"):
    return await outbox.enqueue_email(
        db,
        to=to,
        subject="Hello",
        html="<p>Hello</p>",
        text="Hello",
        kind="welcome",
        idempotency_key=key,
    )


async def test_enqueue_is_idempotent(db):
    first = await _enqueue(db)
    second = await _enqueue(db)

    assert first
    assert first == second
    rows = (await db.execute(select(EmailOutbox))).scalars().all()
    assert len(rows) == 1
    assert rows[0].status == "queued"


async def test_suppressed_address_is_not_enqueued(db):
    await outbox.suppress(db, "blocked@example.com", "bounce", "hard bounce")
    await db.commit()

    queued = await _enqueue(db, to="blocked@example.com", key="welcome:blocked@example.com")

    assert queued is None
    assert (await db.execute(select(EmailOutbox))).scalars().all() == []
    events = (await db.execute(select(EmailEvent))).scalars().all()
    assert any(e.type == "suppressed" for e in events)


async def test_invalid_address_is_rejected(db):
    with pytest.raises(ValueError):
        await _enqueue(db, to="not-an-email", key="bad")


async def test_worker_marks_sent_on_success(db, monkeypatch):
    monkeypatch.setattr("app.database.async_session", _factory(db))
    queued = await _enqueue(db)

    async def fake_deliver(row):
        return "resend-1"

    monkeypatch.setattr(outbox, "_deliver", fake_deliver)
    processed = await outbox.process_once(limit=5)

    assert processed == 1
    row = await db.get(EmailOutbox, queued)
    await db.refresh(row)
    assert row.status == "sent"
    assert row.provider_id == "resend-1"
    assert row.attempts == 1


async def test_transient_failure_requeues_and_permanent_dead_letters(db, monkeypatch):
    monkeypatch.setattr("app.database.async_session", _factory(db))
    row_id = await _enqueue(db)

    async def transient(row):
        raise outbox._Transient("429")

    monkeypatch.setattr(outbox, "_deliver", transient)
    await outbox.process_once(limit=5)
    row = await db.get(EmailOutbox, row_id)
    await db.refresh(row)
    assert row.status == "queued"
    assert row.attempts == 1
    assert row.next_attempt_at is not None

    async def permanent(row):
        raise outbox._Permanent("400 invalid recipient")

    monkeypatch.setattr(outbox, "_deliver", permanent)
    # Make it due immediately so the claim picks it up.
    row.next_attempt_at = datetime.now(timezone.utc)
    await db.commit()
    await outbox.process_once(limit=5)
    await db.refresh(row)
    assert row.status == "dead"


async def _stranded_row(db, *, attempts: int = 1, max_attempts: int = 6) -> str:
    row_id = await _enqueue(db, key="stranded")
    row = await db.get(EmailOutbox, row_id)
    row.status = "sending"
    row.attempts = attempts
    row.max_attempts = max_attempts
    row.claimed_at = datetime.now(timezone.utc) - timedelta(
        seconds=outbox.STALE_SENDING_SECONDS + 1
    )
    await db.commit()
    return row_id


async def test_stale_sending_is_requeued(db, monkeypatch):
    monkeypatch.setattr("app.database.async_session", _factory(db))
    row_id = await _stranded_row(db)

    assert await outbox.requeue_stale_sending() == 1

    row = await db.get(EmailOutbox, row_id)
    await db.refresh(row)
    assert row.status == "queued"
    assert row.claimed_at is None
    assert row.next_attempt_at is not None
    assert "Requeued" in (row.error or "")


async def test_fresh_sending_is_left_alone(db, monkeypatch):
    monkeypatch.setattr("app.database.async_session", _factory(db))
    row_id = await _enqueue(db, key="fresh-sending")
    row = await db.get(EmailOutbox, row_id)
    row.status = "sending"
    row.claimed_at = datetime.now(timezone.utc)
    await db.commit()

    assert await outbox.requeue_stale_sending() == 0

    await db.refresh(row)
    assert row.status == "sending"


async def test_exhausted_stale_sending_becomes_dead(db, monkeypatch):
    monkeypatch.setattr("app.database.async_session", _factory(db))
    row_id = await _stranded_row(db, attempts=6, max_attempts=6)

    assert await outbox.requeue_stale_sending() == 1

    row = await db.get(EmailOutbox, row_id)
    await db.refresh(row)
    assert row.status == "dead"
    assert "retry budget exhausted" in (row.error or "")


async def test_bounce_suppresses_and_duplicate_event_is_ignored(db):
    from app.modules.email.outbox import apply_provider_event

    row = EmailOutbox(
        id="outbox-bounce-000000000000000001",
        to_email="person@example.com",
        subject="Hi",
        html="<p>Hi</p>",
        kind="notification",
        status="sent",
        provider_id="provider-1",
    )
    db.add(row)
    await db.commit()

    await apply_provider_event(
        db,
        event_type="email.bounced",
        provider_id="provider-1",
        email="person@example.com",
        detail="mailbox does not exist",
        provider_event_id="evt-1",
    )
    await db.refresh(row)
    assert row.status == "failed"
    assert await db.get(EmailSuppression, "person@example.com") is not None

    # The same Svix id must not create a second event.
    await apply_provider_event(
        db,
        event_type="email.bounced",
        provider_id="provider-1",
        email="person@example.com",
        provider_event_id="evt-1",
    )
    events = (await db.execute(select(EmailEvent).where(EmailEvent.type == "bounced"))).scalars().all()
    assert len(events) == 1


async def test_unsubscribe_token_round_trip():
    email = "person@example.com"
    token = outbox.unsubscribe_token(email)

    assert outbox.verify_unsubscribe_token(email, token) is True
    assert outbox.verify_unsubscribe_token("other@example.com", token) is False


async def test_dedicated_secret_signs_new_links_and_accepts_legacy(monkeypatch):
    """Rotating JWT_SECRET must not break links already in inboxes."""
    from app.config import settings

    email = "person@example.com"
    # Emulate a link minted before the dedicated key was introduced.
    monkeypatch.setattr(settings, "EMAIL_UNSUBSCRIBE_SECRET", "")
    legacy_token = outbox.unsubscribe_token(email)

    monkeypatch.setattr(settings, "EMAIL_UNSUBSCRIBE_SECRET", "d" * 40)
    new_token = outbox.unsubscribe_token(email)

    assert new_token != legacy_token
    assert outbox.verify_unsubscribe_token(email, new_token) is True
    # A link signed before the dedicated key existed still opts out.
    assert outbox.verify_unsubscribe_token(email, legacy_token) is True
    assert outbox.verify_unsubscribe_token("other@example.com", new_token) is False


async def test_unsubscribe_sets_preference(db, user_id):
    import httpx

    from app.modules.email.router import unsubscribe

    user = User(
        id=user_id,
        email="unsub@example.com",
        first_name="Un",
        last_name="Sub",
        password_hash="x",
        newsletter=True,
    )
    db.add(user)
    await db.commit()

    token = outbox.unsubscribe_token(user.email)
    response = await unsubscribe(email=user.email, token=token, db=db)

    assert response.status_code == 200
    await db.refresh(user)
    assert user.newsletter is False
    assert await db.get(EmailSuppression, user.email) is not None


class _factory:
    """Session factory bound to the test session's engine."""

    def __init__(self, session):
        from sqlalchemy.ext.asyncio import async_sessionmaker

        self._factory = async_sessionmaker(session.bind, expire_on_commit=False)

    def __call__(self):
        return self._factory()

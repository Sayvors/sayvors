"""Durable email queue, retries, suppression and provider events.

The API never talks to Resend on the request path. It writes an outbox row;
``run_email_worker`` claims due rows, sends them with bounded concurrency, and
retries transient failures with exponential backoff. Bounces, complaints and
unsubscribes are permanent suppressions, checked before every enqueue.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import re
import time
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from .models import EmailEvent, EmailOutbox, EmailSuppression

logger = logging.getLogger(__name__)

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
BACKOFF_SECONDS = (60, 300, 1800, 7200, 21600)
POLL_SECONDS = 3.0
# A row is "stranded" when it has been in `sending` longer than any provider
# call could reasonably take (HTTP timeout + queueing). The provider call is
# bounded by httpx, so 15 minutes is already generous.
STALE_SENDING_SECONDS = 15 * 60
REAP_INTERVAL_SECONDS = 60
REAP_BATCH = 100
UNSUBSCRIBE_PATH = "/api/v1/email/unsubscribe"


def normalize_email(value: str | None) -> str | None:
    email = (value or "").strip().lower()
    return email if _EMAIL_RE.match(email) else None


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def is_suppressed(db: AsyncSession, email: str) -> bool:
    row = await db.get(EmailSuppression, normalize_email(email) or "")
    return row is not None


async def suppress(db: AsyncSession, email: str, reason: str, detail: str | None = None) -> None:
    normalized = normalize_email(email)
    if not normalized:
        return
    existing = await db.get(EmailSuppression, normalized)
    if existing is None:
        db.add(EmailSuppression(email=normalized, reason=reason[:24], detail=(detail or "")[:500] or None))
    elif existing.reason != reason:
        existing.reason = reason[:24]
        existing.detail = (detail or "")[:500] or None
    await db.flush()


def _unsubscribe_secrets() -> list[bytes]:
    """Signing keys for unsubscribe links, newest first.

    The dedicated key signs every new link. JWT_SECRET stays in the list as a
    legacy verifier so links sent before this key existed (and before the
    deploy that introduced it) keep working; it is never used to mint new
    links when the dedicated key is configured.
    """
    secrets_out: list[bytes] = []
    for value in (settings.EMAIL_UNSUBSCRIBE_SECRET, settings.JWT_SECRET):
        if value:
            encoded = value.encode("utf-8")
            if encoded not in secrets_out:
                secrets_out.append(encoded)
    return secrets_out or [b"sayvors-email"]


def unsubscribe_token(email: str) -> str:
    normalized = normalize_email(email) or ""
    return hmac.new(
        _unsubscribe_secrets()[0], normalized.encode(), hashlib.sha256
    ).hexdigest()[:40]


def verify_unsubscribe_token(email: str, token: str) -> bool:
    normalized = normalize_email(email) or ""
    presented = (token or "").strip()
    if not presented:
        return False
    # Accept the dedicated key and the legacy JWT-derived key, so a key
    # migration does not break opt-out links already delivered.
    for secret in _unsubscribe_secrets():
        expected = hmac.new(
            secret, normalized.encode(), hashlib.sha256
        ).hexdigest()[:40]
        if hmac.compare_digest(expected, presented):
            return True
    return False


def unsubscribe_url(email: str) -> str:
    # The route lives on the API host. Using the frontend host only works if
    # that host proxies /api/*; staging's Next rewrite targets localhost, so
    # prefer the public API origin.
    base = (
        settings.PUBLIC_API_URL
        or settings.FRONTEND_URL
        or "https://sayvors.com"
    ).rstrip("/")
    from urllib.parse import quote

    return f"{base}{UNSUBSCRIBE_PATH}?email={quote(email)}&token={unsubscribe_token(email)}"


def marketing_headers(email: str) -> dict:
    """One-click unsubscribe headers required for bulk/customer email."""
    return {
        "List-Unsubscribe": f"<{unsubscribe_url(email)}>, <mailto:unsubscribe@sayvors.com>",
        "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
    }


async def enqueue_email(
    db: AsyncSession,
    *,
    to: str,
    subject: str,
    html: str,
    kind: str,
    text: str | None = None,
    tenant_id: str | None = None,
    idempotency_key: str | None = None,
    headers: dict | None = None,
    max_attempts: int = 6,
) -> str | None:
    """Queue one email. Returns the outbox id, or None when suppressed.

    Callers should treat a database error as "email not queued" and surface it;
    a provider error never reaches them.
    """
    email = normalize_email(to)
    if not email:
        raise ValueError("Invalid recipient address.")
    if await is_suppressed(db, email):
        db.add(EmailEvent(email=email, type="suppressed", detail=f"enqueue blocked ({kind})"))
        await db.flush()
        return None
    if idempotency_key:
        existing = (
            await db.execute(
                select(EmailOutbox).where(EmailOutbox.idempotency_key == idempotency_key)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return existing.id

    row = EmailOutbox(
        tenant_id=tenant_id,
        to_email=email,
        subject=(subject or "")[:500],
        html=html,
        text=text,
        kind=(kind or "notification")[:32],
        headers=headers or {},
        idempotency_key=(idempotency_key[:160] if idempotency_key else None),
        max_attempts=max(1, min(int(max_attempts), 10)),
        next_attempt_at=_now(),
    )
    db.add(row)
    try:
        await db.commit()
    except IntegrityError:
        # Concurrent enqueue with the same idempotency key: return the winner.
        await db.rollback()
        if not idempotency_key:
            raise
        existing = (
            await db.execute(
                select(EmailOutbox).where(EmailOutbox.idempotency_key == idempotency_key)
            )
        ).scalar_one_or_none()
        return existing.id if existing is not None else None
    db.add(EmailEvent(outbox_id=row.id, email=email, type="queued", detail=kind[:24]))
    await db.commit()
    return row.id


async def _deliver(row: EmailOutbox) -> str:
    """Send one row through Resend. Raises on failure."""
    if not (settings.RESEND_API_KEY or "").strip():
        raise RuntimeError("RESEND_API_KEY is not configured")

    payload: dict = {
        "from": settings.RESEND_FROM,
        "to": [row.to_email],
        "subject": row.subject,
        "html": row.html,
    }
    if row.text:
        payload["text"] = row.text
    if row.headers:
        payload["headers"] = row.headers

    headers = {
        "Authorization": f"Bearer {settings.RESEND_API_KEY}",
        "Content-Type": "application/json",
    }
    if row.idempotency_key:
        headers["Idempotency-Key"] = row.idempotency_key[:256]

    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(settings.RESEND_URL, headers=headers, json=payload)
    if resp.status_code >= 400:
        detail = resp.text[:300]
        if resp.status_code == 429 or resp.status_code >= 500:
            raise _Transient(f"Resend {resp.status_code}: {detail}")
        raise _Permanent(f"Resend {resp.status_code}: {detail}")
    return str(resp.json().get("id") or "")


class _Transient(Exception):
    pass


class _Permanent(Exception):
    pass


def _backoff(attempts: int) -> datetime:
    index = min(max(0, attempts - 1), len(BACKOFF_SECONDS) - 1)
    return _now() + timedelta(seconds=BACKOFF_SECONDS[index])


async def _mark_sent(row_id: str, provider_id: str) -> None:
    from ...database import async_session

    async with async_session() as db:
        row = await db.get(EmailOutbox, row_id)
        if row is None:
            return
        row.status = "sent"
        row.provider_id = provider_id[:120] or row.provider_id
        row.sent_at = _now()
        row.error = None
        db.add(EmailEvent(outbox_id=row.id, email=row.to_email, type="sent", provider_event_id=None))
        await db.commit()


async def _mark_failure(row_id: str, error: Exception) -> None:
    from ...database import async_session

    transient = isinstance(error, _Transient) or isinstance(error, (httpx.TimeoutException, httpx.TransportError))
    async with async_session() as db:
        row = await db.get(EmailOutbox, row_id)
        if row is None:
            return
        row.error = str(error)[:500]
        if transient and row.attempts < row.max_attempts:
            row.status = "queued"
            row.next_attempt_at = _backoff(row.attempts)
        else:
            row.status = "dead"
        status = row.status
        db.add(EmailEvent(outbox_id=row.id, email=row.to_email, type="failed", detail=str(error)[:300]))
        await db.commit()
        logger.warning(
            "Email %s %s (%s attempts): %s",
            status, row_id, row.attempts, error,
        )


async def process_once(limit: int | None = None) -> int:
    """Claim and deliver one batch. Returns the number of rows processed."""
    from ...database import async_session

    batch = max(1, min(int(limit or settings.EMAIL_WORKER_BATCH), 100))
    async with async_session() as db:
        due = (
            await db.execute(
                select(EmailOutbox.id)
                .where(
                    EmailOutbox.status == "queued",
                    EmailOutbox.next_attempt_at <= _now(),
                )
                .order_by(EmailOutbox.next_attempt_at)
                .limit(batch)
                .with_for_update(skip_locked=True)
            )
        ).scalars().all()
        if not due:
            return 0
        await db.execute(
            update(EmailOutbox)
            .where(EmailOutbox.id.in_(due))
            .values(
                status="sending",
                attempts=EmailOutbox.attempts + 1,
                claimed_at=_now(),
            )
        )
        await db.commit()

    semaphore = asyncio.Semaphore(max(1, settings.EMAIL_WORKER_CONCURRENCY))

    async def _send_one(row_id: str) -> None:
        async with semaphore:
            from ...database import async_session

            async with async_session() as db:
                row = await db.get(EmailOutbox, row_id)
                if row is None or row.status != "sending":
                    return
                try:
                    provider_id = await _deliver(row)
                    await _mark_sent(row_id, provider_id)
                except Exception as e:  # noqa: BLE001 - classified into retry/dead
                    await _mark_failure(row_id, e)

    await asyncio.gather(*(_send_one(row_id) for row_id in due))
    return len(due)


async def requeue_stale_sending(limit: int | None = None) -> int:
    """Return rows stranded in `sending` by a crashed worker to the queue.

    A worker commits `sending` before calling Resend. If the process dies in
    that window, the claim query (which only takes `queued`) never revisits the
    row. Replaying is safe because the provider request carries the outbox
    row's `Idempotency-Key`. Attempts are not incremented here; the next claim
    does that, so the normal retry budget still applies.
    """
    from ...database import async_session

    batch = max(1, min(int(limit or REAP_BATCH), REAP_BATCH))
    now = _now()
    cutoff = now - timedelta(seconds=STALE_SENDING_SECONDS)
    async with async_session() as db:
        rows = (
            await db.execute(
                select(EmailOutbox)
                .where(
                    EmailOutbox.status == "sending",
                    EmailOutbox.claimed_at.is_not(None),
                    EmailOutbox.claimed_at < cutoff,
                )
                .order_by(EmailOutbox.claimed_at)
                .limit(batch)
                .with_for_update(skip_locked=True)
            )
        ).scalars().all()
        if not rows:
            return 0
        for row in rows:
            if row.attempts >= row.max_attempts:
                row.status = "dead"
                row.error = "Worker stopped after claiming; retry budget exhausted"
            else:
                row.status = "queued"
                row.next_attempt_at = now
                row.error = "Requeued after worker restart"
            row.claimed_at = None
            db.add(row)
        await db.commit()
        logger.warning("Requeued %s email(s) stranded in sending", len(rows))
        return len(rows)


async def run_email_worker() -> None:
    logger.info("Email outbox worker started")
    last_reap = 0.0
    while True:
        try:
            now_mono = time.monotonic()
            if now_mono - last_reap >= REAP_INTERVAL_SECONDS:
                last_reap = now_mono
                await requeue_stale_sending()
            processed = await process_once()
            if not processed:
                await asyncio.sleep(POLL_SECONDS)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Email outbox loop failed")
            await asyncio.sleep(POLL_SECONDS)


# ── Provider events ─────────────────────────────────────────────────────


async def apply_provider_event(
    db: AsyncSession,
    *,
    event_type: str,
    provider_id: str | None,
    email: str | None,
    detail: str | None = None,
    provider_event_id: str | None = None,
) -> None:
    """Record a Resend webhook event and update the outbox/suppression state."""
    target = (event_type or "").replace("email.", "")
    normalized = normalize_email(email)

    if provider_event_id:
        seen = (
            await db.execute(
                select(EmailEvent.id).where(EmailEvent.provider_event_id == provider_event_id)
            )
        ).scalar_one_or_none()
        if seen is not None:
            return

    row = None
    if provider_id:
        row = (
            await db.execute(select(EmailOutbox).where(EmailOutbox.provider_id == provider_id))
        ).scalar_one_or_none()
    if row is not None:
        normalized = normalized or row.to_email
        if target == "delivered":
            row.status = "sent"
            row.sent_at = row.sent_at or _now()
        elif target == "bounced":
            row.status = "failed"
            row.error = (detail or "bounced")[:500]
        elif target == "complained":
            row.status = "failed"
            row.error = (detail or "complained")[:500]

    if normalized:
        if target in ("bounced", "complained"):
            await suppress(db, normalized, target, detail)
        elif target == "unsubscribed":
            await suppress(db, normalized, "unsubscribe", detail)
            from ..users.models import User

            await db.execute(
                update(User).where(func.lower(User.email) == normalized).values(newsletter=False)
            )
        db.add(EmailEvent(
            outbox_id=row.id if row is not None else None,
            email=normalized,
            type=target[:24] or "event",
            provider_event_id=provider_event_id,
            detail=(detail or "")[:1000] or None,
        ))
    await db.commit()


async def email_stats(db: AsyncSession, days: int = 7) -> dict:
    since = _now() - timedelta(days=max(1, min(days, 90)))
    by_status = (
        await db.execute(
            select(EmailOutbox.status, func.count())
            .where(EmailOutbox.created_at >= since)
            .group_by(EmailOutbox.status)
        )
    ).all()
    by_event = (
        await db.execute(
            select(EmailEvent.type, func.count())
            .where(EmailEvent.created_at >= since)
            .group_by(EmailEvent.type)
        )
    ).all()
    events = {str(event): int(count) for event, count in by_event}
    return {
        "days": days,
        "outbox": {str(status): int(count) for status, count in by_status},
        "events": events,
        "suppressed": int(
            (await db.execute(select(func.count()).select_from(EmailSuppression))).scalar() or 0
        ),
    }

"""Recovery for AI replies stranded after the outbox retry budget ran out.

LAUNCH-B2/B3 made a lost reply re-drivable: a transient failure leaves the
inbound row ``ai_reply_status='pending'`` and a retry of the same event resumes
it. But a retry is only attempted while the outbox event is pending or failed —
once ``mark_failed`` declares it dead, no further delivery happens, and the row
can sit pending forever with nobody watching.

This sweep closes that tail. The dead outbox row still carries the original
normalized envelope, so recovery re-enqueues that exact payload rather than
trying to reconstruct it from encrypted columns. Re-delivery goes through the
same idempotent consumer path, including its sent-before-crash guard, so a
reply that actually landed is never sent twice. Rows that exhaust the recovery
budget are marked failed and announced instead of silently rotting.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from ...database import async_session
from ..outbox.models import EventOutbox
from ..outbox.service import enqueue_event_in

logger = logging.getLogger(__name__)

DEAD_EVENT_TYPE = "meta.message.received"
# Longer than the largest dispatch backoff, so we only touch events that have
# genuinely stopped being retried rather than ones merely waiting.
RECOVERY_AFTER_MINUTES = 30
# Two re-drives is enough for a transient provider outage. Beyond that the
# problem is not transient and a human needs to see it.
MAX_RECOVERY_ATTEMPTS = 2
RECOVERY_BATCH = 100
RECOVERED_STATUS = "recovered"


async def recover_stranded_replies() -> dict[str, int]:
    """Re-drive dead reply events whose inbound row still owes a reply.

    Returns counts for logging/metrics. Never raises for a single bad row: one
    malformed event must not stop the rest of the batch.
    """
    from .models import ChannelMessage

    stats = {"scanned": 0, "redriven": 0, "flagged": 0, "settled": 0}
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=RECOVERY_AFTER_MINUTES)

    async with async_session() as db:
        dead = (
            await db.execute(
                select(EventOutbox)
                .where(
                    EventOutbox.event_type == DEAD_EVENT_TYPE,
                    EventOutbox.status == "dead",
                    EventOutbox.created_at < cutoff,
                )
                .order_by(EventOutbox.created_at)
                .limit(RECOVERY_BATCH)
            )
        ).scalars().all()

        for event in dead:
            stats["scanned"] += 1
            try:
                envelope = event.payload or {}
                wamid = str(envelope.get("external_event_id") or "")[:200]
                row = None
                if wamid:
                    row = (
                        await db.execute(
                            select(ChannelMessage).where(
                                ChannelMessage.platform_message_id == wamid
                            )
                        )
                    ).scalar_one_or_none()

                # Terminal row (or no row at all) means nothing is owed any
                # more. Retire the dead event so we stop rechecking it.
                if row is None or row.ai_reply_status != "pending":
                    event.status = RECOVERED_STATUS
                    db.add(event)
                    stats["settled"] += 1
                    continue

                attempts = int(row.ai_reply_attempts or 0)
                if attempts >= MAX_RECOVERY_ATTEMPTS:
                    row.ai_reply_status = "failed"
                    row.ai_reply_error = (
                        f"reply recovery exhausted after {attempts} re-drive(s)"
                    )
                    db.add(row)
                    event.status = RECOVERED_STATUS
                    db.add(event)
                    await _announce_failure(db, row, envelope)
                    await db.commit()
                    stats["flagged"] += 1
                    continue

                await enqueue_event_in(
                    db,
                    event_type=event.event_type,
                    payload=envelope,
                    topic=event.topic,
                    dedupe_key=f"reply-recovery:{event.id}:{attempts}",
                )
                row.ai_reply_attempts = attempts + 1
                db.add(row)
                event.status = RECOVERED_STATUS
                db.add(event)
                stats["redriven"] += 1
                await db.commit()
            except Exception as e:  # noqa: BLE001 - never block the batch
                await db.rollback()
                logger.warning(
                    "Reply recovery failed for outbox event %s: %s", event.id, e
                )

        # The redrive and flag branches commit as they go; the settle branch
        # only retires an event, so persist those changes too.
        await db.commit()

    if stats["redriven"] or stats["flagged"]:
        logger.info("Reply recovery: %s", stats)
    return stats


async def _announce_failure(db, row, envelope: dict) -> None:
    """Best-effort bell for the tenant and the platform operator."""
    try:
        from ..notifications.service import notify

        tenant_id = str(envelope.get("tenant_id") or "")
        if not tenant_id:
            return
        await notify(
            db,
            tenant_id,
            "reply_failed",
            "Could not answer a customer message",
            "Automatic reply did not succeed after several attempts. Please check the inbox.",
            data={"channel_id": row.channel_id, "message_id": row.id},
            href="/dashboard/inbox",
        )
    except Exception as e:  # noqa: BLE001 - notification is best effort
        logger.warning("Reply recovery notification failed: %s", e)

    try:
        from ..admin.service import create_admin_notification
        from ...database import async_session as _session

        async with _session() as admin_db:
            await create_admin_notification(
                admin_db,
                kind="ai_reply",
                severity="error",
                title="AI reply stranded",
                body=(
                    f"Reply for channel {row.channel_id} exhausted recovery; "
                    f"message {row.id} needs an operator."
                ),
                href="/dashboard/analytics",
            )
    except Exception as e:  # noqa: BLE001 - operator bell is best effort
        logger.warning("Reply recovery admin notification failed: %s", e)

"""Real-time + bell notifications for review tickets.

A ticket's whole life happens outside the browser tab that created it: the
reviews worker classifies a review and mints a ticket while nobody is looking,
and the customer walks back in on WhatsApp minutes or hours later. Without an
out-of-band signal the queue is a page you have to remember to reload, so a
merchant can sit on an unresolved refund review without noticing it exists.

Two channels, deliberately different:

1. **Realtime (`review_issue` events).** Published on every lifecycle change so
   open queues and dashboard cards update themselves. Cheap and lossy: a missed
   publish only means the next fetch is stale.
2. **Bell notifications.** Persisted rows for the handful of moments a human
   actually has to act on. Lossy events are fine; a lost notification is not,
   hence the DB row the bell reads on its poll.

`handoff_minted` is realtime-only. It fires seconds after `created` on the same
ticket, so a second bell entry would be the same news twice — the queue row
already shows the code the moment it exists.

Everything here is best-effort and never raises. A Redis hiccup, a notification
insert failure or a Redis-down publish must not roll back a review pipeline, a
merchant's status change, or a customer's WhatsApp reply.
"""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

QUEUE_HREF = "/dashboard/reviews/issues"

# Event actions. Stable strings: the browser switches on them.
CREATED = "created"
UPDATED = "updated"
CUSTOMER_RETURNED = "customer_returned"
HANDOFF_MINTED = "handoff_minted"

_TYPE_BY_ACTION = {
    CREATED: "review_ticket_created",
    UPDATED: "review_ticket_updated",
    CUSTOMER_RETURNED: "review_ticket_customer",
}


def _label(value) -> str:
    return str(value or "").replace("_", " ").strip()


def issue_payload(issue) -> dict:
    """The slice of a ticket a browser needs to redraw its queue.

    Deliberately not the whole row: no review text, no summary of what the
    customer wrote. Consumers refetch on the event rather than trusting this
    payload to render from, so it only has to be enough to tell the client
    *that* something moved and which row it was.
    """
    created = getattr(issue, "created_at", None)
    return {
        "id": getattr(issue, "id", None),
        "ticket_number": getattr(issue, "ticket_number", None),
        "status": getattr(issue, "status", None),
        "priority": getattr(issue, "priority", None),
        "needs_attention": bool(getattr(issue, "needs_attention", False)),
        "primary_category": getattr(issue, "primary_category", None),
        "subcategory": getattr(issue, "subcategory", None),
        "rating": getattr(issue, "rating", None),
        "has_handoff_code": bool(getattr(issue, "handoff_code", None)),
        "created_at": created.isoformat() if hasattr(created, "isoformat") else None,
    }


async def publish_review_issue_event(tenant_id: str, issue, action: str) -> None:
    """Fan one lifecycle change out to every open queue for this tenant."""
    try:
        from .realtime import publish_inbox_event

        await publish_inbox_event(
            tenant_id,
            {
                "type": "review_issue",
                "action": action,
                "issue": issue_payload(issue),
            },
        )
    except Exception as e:  # noqa: BLE001 — realtime must never break the caller
        logger.debug("review_issue event %s skipped: %s", action, e)


def _describe(issue, action: str) -> tuple[str, str]:
    """(title, body) for the bell entry. Ticket number leads so the merchant
    can match it against the queue without opening the notification."""
    ticket = getattr(issue, "ticket_number", None) or "Review issue"
    if action == CREATED:
        summary = getattr(issue, "summary", None) or getattr(issue, "review_text", None)
        rating = getattr(issue, "rating", None)
        category = _label(getattr(issue, "primary_category", None))
        bits = [b for b in (f"{rating}★" if rating else "", category) if b]
        detail = " · ".join(bits)
        body = (summary or detail or "Needs a reply").strip()
        return f"New ticket {ticket}", body[:160]
    if action == CUSTOMER_RETURNED:
        return (
            f"{ticket}: customer replied",
            "They came back on WhatsApp — the ticket is now open.",
        )
    return f"{ticket} updated", f"Status is now {_label(getattr(issue, 'status', ''))}."


async def notify_review_issue(
    db: AsyncSession,
    *,
    tenant_id: str,
    issue,
    action: str,
    actor_user_id: str | None = None,
) -> str | None:
    """Write (and announce) one bell entry for a ticket change. Returns its id.

    Skipped, deliberately:
      * `handoff_minted` — realtime only, see the module docstring;
      * the workspace owner changing their own ticket — they are looking at the
        row they just clicked, and a bell entry for it is noise;
      * tenants who switched the "Review tickets" preference off.

    Never raises: `notify()` writes inside a savepoint, and the realtime
    publish swallows its own failures, so a bad event can cost at most the
    notification — never the review pipeline or the customer's reply.
    """
    if action not in _TYPE_BY_ACTION:
        return None
    if actor_user_id is not None and actor_user_id == tenant_id:
        return None

    try:
        from ..notifications.service import normalize_notification_settings, notify
        from ..users.models import User

        prefs = (
            await db.execute(
                select(User.notification_settings).where(User.id == tenant_id)
            )
        ).scalar_one_or_none()
        if not normalize_notification_settings(prefs)["tickets"]:
            return None

        title, body = _describe(issue, action)
        nid = await notify(
            db,
            tenant_id,
            _TYPE_BY_ACTION[action],
            title,
            body,
            data={
                "issue_id": getattr(issue, "id", None),
                "ticket_number": getattr(issue, "ticket_number", None),
                "status": getattr(issue, "status", None),
                "action": action,
            },
            href=QUEUE_HREF,
        )
        if nid is None:
            return None

        from .realtime import publish_inbox_event

        await publish_inbox_event(
            tenant_id,
            {
                "type": "notification",
                "notification": {
                    "kind": "review_ticket",
                    "notification_id": nid,
                    "ticket_number": getattr(issue, "ticket_number", None),
                    "preview": body,
                    "action": action,
                },
            },
        )
        return nid
    except Exception as e:  # noqa: BLE001 — a notification must not break a commit
        logger.warning("review ticket notification (%s) failed: %s", action, e)
        return None
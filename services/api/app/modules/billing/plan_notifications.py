"""Sales notification for Enterprise plan requests.

A tenant asking for Enterprise is a lead, not a checkout: the purchase is
completed by a human over email, phone or a meeting. This module emails the
operator-configured sales list with enough contact detail to start that
conversation.

Delivery goes through the email outbox, never inline: the tenant's request
returns as soon as the outbox rows exist and the worker owns retries. One row
per recipient keeps a single bad inbox from hiding the rest, and the
idempotency key (request + address) makes a retried request harmless.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from ..users.models import User
from .models import BillingRequest

logger = logging.getLogger(__name__)


def _one_line(value: str) -> str:
    """Collapse whitespace so user-supplied names cannot break a mail subject."""
    return " ".join((value or "").split())


def _display_name(tenant: User) -> str:
    person = _one_line(f"{tenant.first_name or ''} {tenant.last_name or ''}")
    return _one_line(tenant.business_name or person or tenant.email or "Unknown tenant")


def build_enterprise_request_email(
    request: BillingRequest,
    tenant: User,
    *,
    requested_by: User | None = None,
) -> tuple[str, str]:
    """Return (subject, plain-text body) for one Enterprise request.

    ``tenant`` is the workspace owner (the billing contact), not necessarily
    the employee who clicked the button; ``requested_by`` adds who submitted it
    when the two differ, so sales knows who to reply to first.
    """
    name = _display_name(tenant)
    person = _one_line(f"{tenant.first_name or ''} {tenant.last_name or ''}")
    requested_at = request.created_at or datetime.now(timezone.utc)

    lines = [
        f"{name} just requested the Enterprise plan.",
        "",
        f"Business: {tenant.business_name or '-'}",
        f"Contact: {person or '-'}",
        f"Email: {tenant.email or '-'}",
        f"Phone: {tenant.phone or '-'}",
        "Plan requested: Enterprise",
        f"Request ID: {request.id}",
        f"Requested: {requested_at.strftime('%Y-%m-%d %H:%M UTC')}",
    ]
    if requested_by is not None and requested_by.id != tenant.id:
        lines.append(f"Requested by: {requested_by.email or requested_by.id}")
    if request.note:
        lines += ["", "What they wrote:", request.note]
    lines += ["", "Follow up by email, phone, or a meeting link."]

    return f"Enterprise plan request: {name}"[:200], "\n".join(lines)


def _sanitize_address(address: str) -> str:
    """Keep a validated address from breaking the log line it lands in."""
    return address.replace("\r", "").replace("\n", "")[:320]


async def notify_enterprise_request(
    db: AsyncSession, *, request: BillingRequest, requested_by: User | None = None
) -> int:
    """Queue one email per configured recipient; return how many were queued.

    Best effort by design: the request is already committed and must not fail
    because email is down or the list is empty. Every skipped address is
    logged with the request id so a missing notification is diagnosable rather
    than silent.
    """
    from ..admin.enterprise_recipients import recipient_emails
    from ..email.service import send_notification_email

    # Billing belongs to the workspace owner. Resolve the owner from the
    # request's tenant id so an employee's request still reaches the right
    # billing contact (and the employee is named as the submitter).
    tenant = await db.get(User, request.tenant_id) or requested_by
    if tenant is None:
        logger.warning(
            "Enterprise request %s has no tenant row; not emailing sales",
            request.id,
        )
        return 0

    recipients = await recipient_emails(db)
    if not recipients:
        logger.warning(
            "Enterprise request %s has no notification recipients configured",
            request.id,
        )
        return 0

    subject, body = build_enterprise_request_email(
        request, tenant, requested_by=requested_by
    )
    admin_url = (settings.ADMIN_CONSOLE_URL or "").strip().rstrip("/")
    # No console URL means no useful CTA; do not silently point sales at the
    # tenant web app via _resolve_cta's FRONTEND_URL fallback.
    cta = f"{admin_url}/requests" if admin_url else None

    queued = 0
    for address in recipients:
        try:
            await send_notification_email(
                address,
                subject,
                body,
                cta,
                idempotency_key=f"enterprise-request:{request.id}:{address}",
            )
            queued += 1
        except Exception as e:  # noqa: BLE001 - one address must not stop the rest
            logger.warning(
                "Enterprise request %s email to %s failed: %s",
                request.id,
                _sanitize_address(address),
                e,
            )

    if queued:
        logger.info(
            "Enterprise request %s emailed to %d recipient(s)", request.id, queued
        )
    return queued

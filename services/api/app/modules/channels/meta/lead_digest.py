"""Pending-leads digest: one summary email per tenant per local day.

Escalation emails are per-event and per-lead: they fire the moment one thread
goes wrong. That covers the urgent case and nothing else. A tenant with forty
qualified leads and no escalations hears nothing at all, so the leads quietly
sit there — which is the failure this exists to prevent.

What counts as pending is deliberately narrow: `qualified` and `follow_up`,
not opted out. `converted` and `lost` are terminal, and `new` has not shown
buying intent yet, so a digest that listed it would be noise about contacts
who asked nothing.

Two properties matter more than the content:

* **Once per local day, enforced by the database.** `lead_digest_sends` has
  UNIQUE (tenant_id, digest_date), so a second send is not a race to guard but
  an insert that cannot happen. Several workers may run this sweep and one may
  restart mid-send.
* **Nothing when there is nothing to say.** A tenant with no pending leads gets
  no email, because "you have 0 leads" every morning trains people to ignore
  the sender.

`digest_date` is the tenant's LOCAL calendar date and the send hour is their
local hour, so a Riyadh tenant gets theirs at 08:00 Riyadh time rather than
whenever UTC happens to roll over.
"""

import logging
import uuid
from datetime import date as date_cls
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from ..models import Lead, LeadDigestSend
from .lead_engine import category_label
from .lead_escalation import _send_email, load_settings

logger = logging.getLogger(__name__)

# Terminal stages never appear. `new` is excluded too: it has not demonstrated
# buying intent, so a summary built on it is a contact list, not a leads list.
PENDING_STAGES = ("qualified", "follow_up")

# Bounded so one tenant cannot produce an unbounded query or an unbounded
# email. Overridable per tenant via digest_max_leads.
DEFAULT_MAX_LEADS = 20

# Tenants per sweep tick. The sweep is called repeatedly, so a cap just bounds
# one pass; nothing is left unsent, only deferred to the next tick.
TENANTS_PER_TICK = 25

DIGEST_SUBJECT = "{count} lead{plural} still waiting"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def local_now(tz_name: str) -> datetime:
    """Now in the tenant's timezone. Unknown zones fall back to UTC.

    normalize_lead_settings already rejects a zone it cannot load, so this is
    belt and braces for settings written before that clamp existed.
    """
    try:
        return _now().astimezone(ZoneInfo(tz_name))
    except Exception:
        return _now()


def _due(local: datetime, hour: int) -> bool:
    """Has the tenant's digest hour arrived today?

    `local.hour >= hour` is deliberately not `==`: a sweep that was down at
    08:00 would otherwise skip the whole day. After the hour it stays due for
    the rest of the local day, which is exactly once because the unique
    constraint absorbs the repeats.
    """
    return local.hour >= hour


def _waited_for(lead: Lead, local: datetime) -> str:
    """Human-scale 'how long has this been sitting', for the email body."""
    ref = lead.last_message_at or lead.created_at
    if ref is None:
        return "unknown"
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    delta = local.astimezone(timezone.utc) - ref
    hours = delta.total_seconds() / 3600
    if hours < 1:
        return f"{int(delta.total_seconds() // 60)}m"
    if hours < 24:
        return f"{int(hours)}h"
    # Days rather than "48h": a lead waiting two days reads as two days.
    return f"{int(hours // 24)}d"


def _label(lead: Lead) -> str:
    return (
        lead.contact_name
        or lead.contact_username
        or lead.contact_id
        or "Unknown contact"
    )


async def _pending_tenants(db, today: date_cls, limit: int = TENANTS_PER_TICK) -> list[str]:
    """Tenants with at least one pending lead and no digest today.

    Driven off `leads` rather than `users`: a tenant with no pending leads is
    not a row we need to visit, so the common case costs one indexed scan
    instead of a pass over every tenant in the system.
    """
    rows = (
        await db.execute(
            select(Lead.tenant_id)
            .where(
                Lead.stage.in_(PENDING_STAGES),
                Lead.opt_out.is_(False),
            )
            .distinct()
        )
    ).scalars().all()

    candidates = [t for t in rows if t]
    if not candidates:
        return []

    # One indexed lookup for the batch rather than a query per tenant.
    already = (
        await db.execute(
            select(LeadDigestSend.tenant_id).where(
                LeadDigestSend.digest_date == today,
                LeadDigestSend.tenant_id.in_(candidates),
            )
        )
    ).scalars().all()

    return [t for t in candidates if t not in set(already)][:limit]


async def _pending_leads(db, tenant_id: str, limit: int) -> list[Lead]:
    """This tenant's pending leads, most urgent first.

    Ordered on a boolean rather than the enum: `priority` is a Postgres enum
    whose sort order is its definition order, so ordering by the column would
    put 'important' first only by accident. An escalated thread is waiting on a
    human right now; the rest go stalest-first, because the lead nobody has
    touched is the one a summary exists to surface.
    """
    stmt = (
        select(Lead)
        .where(
            Lead.tenant_id == tenant_id,
            Lead.stage.in_(PENDING_STAGES),
            Lead.opt_out.is_(False),
            # Merged rows are the same person on another channel — see
            # _count_pending.
            Lead.merged_into_id.is_(None),
        )
        .order_by(
            (Lead.priority == "important").desc(),
            Lead.last_message_at.asc().nullsfirst(),
        )
        .limit(limit)
    )
    return list((await db.execute(stmt)).scalars().all())


def compose_digest(leads: list[Lead], local: datetime, truncated: int = 0) -> tuple[str, str]:
    """Subject and plain-text body. Returns (subject, body)."""
    count = len(leads)
    subject = DIGEST_SUBJECT.format(count=count, plural="" if count == 1 else "s")

    lines = [
        f"{count} lead{'' if count == 1 else 's'} still waiting on you.",
        "",
    ]
    for lead in leads:
        label = _label(lead)
        category = category_label(getattr(lead, "category", None))
        if category:
            label = f"{label} [{category}]"
        bits = [
            label,
            f"({lead.platform}, waiting { _waited_for(lead, local) })",
        ]
        if lead.priority == "important":
            bits.append("[needs you now]")
        line = " - ".join(bits)
        if lead.request:
            line += f"\n    asked: {lead.request.strip()[:160]}"
        lines.append(f"  * {line}")

    if truncated:
        lines.append("")
        lines.append(f"  ... and {truncated} more waiting.")

    lines.append("")
    lines.append("Nothing here is urgent unless marked 'needs you now'.")
    lines.append("Converted and lost leads are not listed.")
    return subject, "\n".join(lines)


async def run_digest_sweep(db, limit: int | None = None) -> int:
    """Send at most one digest per due tenant. Returns how many were sent.

    Never raises: a failed digest must not take the worker down, and must not
    block any other tenant's.
    """
    sent = 0
    settings_cache: dict[str, dict] = {}

    for tenant_id in await _pending_tenants(db, date_cls.today()):
        try:
            settings = settings_cache.get(tenant_id)
            if settings is None:
                settings = await load_settings(db, tenant_id)
                settings_cache[tenant_id] = settings

            if not settings.get("digest_enabled"):
                continue

            tz = settings.get("timezone") or "UTC"
            local = local_now(tz)
            if not _due(local, int(settings.get("digest_hour", 8))):
                continue

            today = local.date()
            if await _already_sent(db, tenant_id, today):
                continue

            max_leads = int(settings.get("digest_max_leads", DEFAULT_MAX_LEADS))
            leads = await _pending_leads(db, tenant_id, max_leads)
            if not leads:
                # Claim the day anyway: otherwise this tenant re-enters every
                # tick and the sweep does the same work forever.
                await _claim(db, tenant_id, today, 0)
                await db.commit()
                continue

            total = await _count_pending(db, tenant_id)
            subject, body = compose_digest(leads, local, truncated=max(0, total - len(leads)))

            recipients = await _resolve(db, tenant_id)
            if not recipients:
                logger.warning("lead digest for %s has no recipient", tenant_id)
                await _claim(db, tenant_id, today, 0)
                await db.commit()
                continue

            # Claim BEFORE sending. If the send then fails the day is still
            # spent, which is deliberate: a retried digest is a second email to
            # a customer about leads they already saw, and a broken mail path
            # would otherwise retry all day.
            await _claim(db, tenant_id, today, len(leads))
            await db.commit()

            await _send_email(
                recipients,
                subject,
                body,
                cta_url="/dashboard/leads",
            )
            sent += 1
            logger.info(
                "lead digest sent tenant=%s leads=%d total=%d",
                tenant_id, len(leads), total,
            )
        except Exception as e:
            logger.warning(
                "lead digest failed for %s: %s: %s",
                tenant_id, type(e).__name__, e,
            )
            try:
                await db.rollback()
            except Exception:
                pass
    return sent


async def _already_sent(db, tenant_id: str, day: date_cls) -> bool:
    row = (
        await db.execute(
            select(LeadDigestSend.id).where(
                LeadDigestSend.tenant_id == tenant_id,
                LeadDigestSend.digest_date == day,
            )
        )
    ).scalar_one_or_none()
    return row is not None


async def _count_pending(db, tenant_id: str) -> int:
    return (
        await db.execute(
            select(func.count())
            .select_from(Lead)
            .where(
                Lead.tenant_id == tenant_id,
                Lead.stage.in_(PENDING_STAGES),
                Lead.opt_out.is_(False),
                # A lead merged into another channel's row is the same person;
                # counting both would inflate every digest.
                Lead.merged_into_id.is_(None),
            )
        )
    ).scalar() or 0


async def _resolve(db, tenant_id: str) -> list[str]:
    """Recipients, reusing the escalation rules so both emails agree.

    Same source: lead_settings.escalation_emails, else the owner's signup
    email. A tenant who configures one and expects it to apply to escalation
    should not discover the digest went somewhere else.
    """
    from ...users.models import User

    configured = (await load_settings(db, tenant_id)).get("escalation_emails") or []
    if configured:
        return list(configured)
    owner = (
        await db.execute(select(User.email).where(User.id == tenant_id))
    ).scalar_one_or_none()
    return [owner] if owner else []


async def _claim(db, tenant_id: str, day: date_cls, lead_count: int) -> bool:
    """Take the day. Returns False if someone already had it."""
    db.add(
        LeadDigestSend(
            id=uuid.uuid4().hex,
            tenant_id=tenant_id,
            digest_date=day,
            lead_count=lead_count,
            created_at=_now(),
        )
    )
    try:
        await db.flush()
        return True
    except IntegrityError:
        await db.rollback()
        return False


__all__ = [
    "PENDING_STAGES",
    "compose_digest",
    "local_now",
    "run_digest_sweep",
]
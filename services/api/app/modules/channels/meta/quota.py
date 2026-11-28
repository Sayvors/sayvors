"""Atomic PostgreSQL quota reservations for every WhatsApp Messages API call.

The monthly row lock is the arbitration point. Redis is deliberately absent:
a cached or fail-open counter cannot enforce a hard plan limit. A reservation
counts before the provider call. Only a proven pre-send transport failure
releases it; Meta HTTP errors and ambiguous mid-flight failures stay charged.
"""
from __future__ import annotations

import hashlib
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date, datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from ...billing.entitlements import ENTITLEMENT_DENIED_HEADER, get_entitlements
from .spend_models import WhatsAppMonthlyUsage, WhatsAppQuotaReservation

_session_factory = None
_send_key: ContextVar[str | None] = ContextVar("whatsapp_send_key", default=None)


@contextmanager
def whatsapp_send_key(key: str):
    """Bind a stable retry key to one logical send without changing adapter APIs."""
    token = _send_key.set(key[:160])
    try:
        yield
    finally:
        _send_key.reset(token)


def current_send_key() -> str | None:
    return _send_key.get()


def current_month() -> date:
    now = datetime.now(timezone.utc)
    return now.replace(day=1).date()


def _factory():
    if _session_factory is not None:
        return _session_factory
    from ....database import async_session
    return async_session


async def _ensure_month_row(db, tenant_id: str, month: date) -> None:
    if db.bind.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert

        await db.execute(
            insert(WhatsAppMonthlyUsage)
            .values(tenant_id=tenant_id, month=month, used_count=0)
            .on_conflict_do_nothing(index_elements=["tenant_id", "month"])
        )
        return
    try:
        async with db.begin_nested():
            db.add(WhatsAppMonthlyUsage(tenant_id=tenant_id, month=month, used_count=0))
            await db.flush()
    except IntegrityError:
        pass


async def _locked_month_row(db, tenant_id: str, month: date):
    await _ensure_month_row(db, tenant_id, month)
    query = select(WhatsAppMonthlyUsage).where(
        WhatsAppMonthlyUsage.tenant_id == tenant_id,
        WhatsAppMonthlyUsage.month == month,
    )
    if db.bind.dialect.name == "postgresql":
        query = query.with_for_update()
    return (await db.execute(query)).scalar_one()


async def reserve_whatsapp_send(
    db, tenant_id: str, phone_number_id: str, idempotency_key: str
) -> WhatsAppQuotaReservation:
    """Reserve one slot atomically; duplicate consumed/reserved keys are free."""
    key = idempotency_key[:160]
    month = current_month()
    usage = await _locked_month_row(db, tenant_id, month)
    existing = (
        await db.execute(
            select(WhatsAppQuotaReservation).where(
                WhatsAppQuotaReservation.tenant_id == tenant_id,
                WhatsAppQuotaReservation.idempotency_key == key,
            )
        )
    ).scalar_one_or_none()
    if existing is not None and existing.status != "released":
        await db.commit()
        return existing

    ent = await get_entitlements(tenant_id, db)
    if not ent.has_feature("messaging"):
        raise HTTPException(
            status_code=403, detail="Messaging is not included in your plan.",
            headers={ENTITLEMENT_DENIED_HEADER: "messaging"},
        )
    if ent.max_messages_per_month is not None and usage.used_count >= ent.max_messages_per_month:
        raise HTTPException(
            status_code=429,
            detail=f"Monthly WhatsApp message limit reached for plan '{ent.plan_slug}'. Upgrade to send more.",
            headers={ENTITLEMENT_DENIED_HEADER: "quota"},
        )
    if existing is None:
        existing = WhatsAppQuotaReservation(
            tenant_id=tenant_id, month=month, idempotency_key=key,
            phone_number_id=phone_number_id, status="reserved",
        )
        db.add(existing)
    else:
        existing.status = "reserved"
        existing.month = month
        existing.phone_number_id = phone_number_id
        existing.failure_classification = None
        existing.settled_at = None
    usage.used_count += 1
    await db.commit()
    await db.refresh(existing)
    return existing


async def settle_whatsapp_reservation(
    db, reservation_id: str, outcome: str, *,
    provider_message_id: str | None = None,
    failure_classification: str | None = None,
) -> WhatsAppQuotaReservation:
    """Consume, or release exactly once for a proven pre-send failure."""
    if outcome not in ("consumed", "released"):
        raise ValueError("outcome must be consumed or released")
    reservation = await db.get(WhatsAppQuotaReservation, reservation_id)
    if reservation is None:
        raise RuntimeError("WhatsApp quota reservation disappeared")
    if reservation.status != "reserved":
        if provider_message_id and not reservation.provider_message_id:
            reservation.provider_message_id = provider_message_id[:200]
            await db.commit()
        return reservation
    if outcome == "released":
        usage = await _locked_month_row(db, reservation.tenant_id, reservation.month)
        usage.used_count -= 1
        reservation.status = "released"
        reservation.failure_classification = failure_classification or "pre_send"
    else:
        reservation.status = "consumed"
    reservation.provider_message_id = (provider_message_id or reservation.provider_message_id)
    if reservation.provider_message_id:
        reservation.provider_message_id = reservation.provider_message_id[:200]
    reservation.settled_at = datetime.now(timezone.utc)
    await db.commit()
    return reservation


async def reconcile_provider_sent(
    db, tenant_id: str, phone_number_id: str, provider_message_id: str
) -> WhatsAppQuotaReservation:
    """Count a provider-confirmed send once, even if local dispatch predates quota."""
    wamid = provider_message_id[:200]
    reconciliation_key = f"provider:{hashlib.sha256(wamid.encode()).hexdigest()}"
    month = current_month()
    usage = await _locked_month_row(db, tenant_id, month)
    reservation = (
        await db.execute(
            select(WhatsAppQuotaReservation).where(
                WhatsAppQuotaReservation.provider_message_id == wamid,
            )
        )
    ).scalar_one_or_none()
    if reservation is None:
        reservation = (
            await db.execute(
                select(WhatsAppQuotaReservation).where(
                    WhatsAppQuotaReservation.tenant_id == tenant_id,
                    WhatsAppQuotaReservation.idempotency_key == reconciliation_key,
                )
            )
        ).scalar_one_or_none()
    if reservation is None:
        reservation = WhatsAppQuotaReservation(
            tenant_id=tenant_id, month=month,
            idempotency_key=reconciliation_key, status="consumed",
            phone_number_id=phone_number_id, provider_message_id=wamid,
            settled_at=datetime.now(timezone.utc),
        )
        db.add(reservation)
        usage.used_count += 1
    elif reservation.status == "released":
        # A prior transport classification was wrong: Meta now proves it sent.
        reservation.status = "consumed"
        reservation.month = month
        reservation.provider_message_id = wamid
        reservation.settled_at = datetime.now(timezone.utc)
        usage.used_count += 1
    elif reservation.status == "reserved":
        reservation.status = "consumed"
        reservation.provider_message_id = wamid
        reservation.settled_at = datetime.now(timezone.utc)
    await db.commit()
    return reservation

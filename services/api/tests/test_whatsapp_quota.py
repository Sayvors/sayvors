"""Atomic WhatsApp quota reservations, settlement policy, and month reset."""
import asyncio
import os
import uuid
from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.modules.billing.models import Plan, TenantSubscription
from app.modules.channels.meta import quota
from app.modules.channels.meta.spend_models import (
    WhatsAppMonthlyUsage, WhatsAppQuotaReservation,
)
from app.modules.users.models import User


async def _seed(db, *, limit=2, bonus=1):
    uid = f"quota-{uuid.uuid4().hex[:8]}"
    plan = Plan(
        id=f"plan-{uid}", slug=f"plan-{uid}", name="Quota Test",
        max_messages_per_month=limit, features={"messaging": True},
    )
    db.add(User(
        id=uid, first_name="Quota", last_name="Test",
        email=f"{uid}@example.com", password_hash="x",
    ))
    db.add(plan)
    await db.flush()
    db.add(TenantSubscription(
        tenant_id=uid, plan_id=plan.id, message_bonus=bonus,
    ))
    await db.commit()
    return uid


@pytest.mark.asyncio
async def test_duplicate_key_does_not_double_count(db):
    uid = await _seed(db)
    first = await quota.reserve_whatsapp_send(db, uid, "pn-1", "same")
    await quota.settle_whatsapp_reservation(db, first.id, "consumed")
    second = await quota.reserve_whatsapp_send(db, uid, "pn-1", "same")
    usage = (await db.execute(
        select(WhatsAppMonthlyUsage).where(WhatsAppMonthlyUsage.tenant_id == uid)
    )).scalar_one()
    assert second.id == first.id
    assert usage.used_count == 1


@pytest.mark.asyncio
async def test_proven_pre_send_failure_releases_exactly_once(db):
    uid = await _seed(db)
    reservation = await quota.reserve_whatsapp_send(db, uid, "pn-1", "connect-fail")
    await quota.settle_whatsapp_reservation(
        db, reservation.id, "released", failure_classification="transport_never_reached"
    )
    await quota.settle_whatsapp_reservation(
        db, reservation.id, "released", failure_classification="transport_never_reached"
    )
    usage = (await db.execute(
        select(WhatsAppMonthlyUsage).where(WhatsAppMonthlyUsage.tenant_id == uid)
    )).scalar_one()
    assert usage.used_count == 0
    stored = await db.get(WhatsAppQuotaReservation, reservation.id)
    assert stored.status == "released"


@pytest.mark.asyncio
async def test_plan_allowance_plus_bonus_and_month_reset(db, monkeypatch):
    uid = await _seed(db, limit=2, bonus=1)
    for index in range(3):
        await quota.reserve_whatsapp_send(db, uid, "pn-1", f"key-{index}")
    with pytest.raises(HTTPException) as error:
        await quota.reserve_whatsapp_send(db, uid, "pn-1", "over-limit")
    assert error.value.status_code == 429
    monkeypatch.setattr(quota, "current_month", lambda: date(2026, 12, 1))
    await quota.reserve_whatsapp_send(db, uid, "pn-1", "next-month")
    rows = (await db.execute(
        select(WhatsAppMonthlyUsage).where(WhatsAppMonthlyUsage.tenant_id == uid)
        .order_by(WhatsAppMonthlyUsage.month)
    )).scalars().all()
    assert [row.used_count for row in rows] == [3, 1]


@pytest.mark.asyncio
async def test_released_transport_failure_is_not_counted_by_existing_gate(db):
    from app.modules.billing.entitlements import count_messages_this_month
    from app.modules.channels.models import Channel, ChannelMessage

    uid = await _seed(db)
    channel = Channel(
        id=f"chan-{uid}", user_id=uid, platform="whatsapp",
        platform_user_id="pn-1", status="active",
    )
    db.add(channel)
    await db.flush()
    db.add(ChannelMessage(
        id=f"msg-{uid}", channel_id=channel.id, direction="outbound",
        content="failed before Meta", status="failed",
    ))
    await db.commit()
    reservation = await quota.reserve_whatsapp_send(db, uid, "pn-1", "never-reached")
    await quota.settle_whatsapp_reservation(db, reservation.id, "released")
    assert await count_messages_this_month(uid, db) == 0


@pytest.mark.asyncio
async def test_postgres_row_lock_serializes_concurrent_reservations():
    url = os.environ.get("WHATSAPP_QUOTA_TEST_DATABASE_URL")
    if not url:
        pytest.skip("WHATSAPP_QUOTA_TEST_DATABASE_URL is not configured")
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from app.database import Base

    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with factory() as db:
            uid = await _seed(db, limit=2, bonus=0)
        semaphore = asyncio.Semaphore(10)

        async def reserve(index):
            async with semaphore, factory() as db:
                try:
                    await quota.reserve_whatsapp_send(db, uid, "pn-1", f"race-{index}")
                    return True
                except HTTPException as exc:
                    return exc.status_code == 429

        outcomes = await asyncio.gather(*(reserve(i) for i in range(10)))
        assert all(outcomes)
        async with factory() as db:
            usage = (await db.execute(
                select(WhatsAppMonthlyUsage).where(WhatsAppMonthlyUsage.tenant_id == uid)
            )).scalar_one()
            assert usage.used_count == 2
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()

"""FACT-9: review campaigns are plan-limited, reusable and measurable."""
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.modules.analytics import campaigns
from app.modules.analytics.models import ReviewCampaign, ReviewRequest
from app.modules.billing.models import Plan

pytestmark = pytest.mark.asyncio


async def _plan(db, *, monthly: int | None, days: int | None, slug="campaign-plan") -> Plan:
    row = Plan(
        id=f"plan-{slug}", slug=slug, name="Campaign Plan",
        max_channels=None, max_messages_per_month=None,
        max_campaigns_per_month=monthly, max_campaign_days=days,
        features={"reviews": True}, is_active=True, sort_order=99,
    )
    db.add(row)
    await db.commit()
    # Point the tenant's subscription at it so get_entitlements resolves it.
    from app.modules.billing.models import TenantSubscription
    db.add(TenantSubscription(tenant_id="tenant-campaigns-1", plan_id=row.id, status="active"))
    await db.commit()
    return row


async def _create(db, **overrides):
    values = dict(
        tenant_id="tenant-campaigns-1", name="Spring push",
        from_date=date.today() + timedelta(days=1),
        to_date=date.today() + timedelta(days=5),
        message_template="Hi {name} — {link}",
    )
    values.update(overrides)
    return await campaigns.create_campaign(db, **values)


def test_status_derives_from_dates():
    today = date(2026, 11, 18)
    mk = lambda s: ReviewCampaign(status=s, from_date=today - timedelta(days=2), to_date=today + timedelta(days=2))
    assert campaigns.campaign_status(mk("scheduled"), today=today) == "active"
    assert campaigns.campaign_status(mk("cancelled"), today=today) == "cancelled"
    future = ReviewCampaign(status="scheduled", from_date=today + timedelta(days=1), to_date=today + timedelta(days=3))
    assert campaigns.campaign_status(future, today=today) == "scheduled"
    past = ReviewCampaign(status="scheduled", from_date=today - timedelta(days=5), to_date=today - timedelta(days=1))
    assert campaigns.campaign_status(past, today=today) == "ended"


async def test_create_enforces_plan_limits(db):
    await _plan(db, monthly=1, days=7)
    first = await _create(db)
    assert first.status == "scheduled"
    with pytest.raises(campaigns.CampaignError, match="per month"):
        await _create(db, name="Second")
    with pytest.raises(campaigns.CampaignError, match="up to 7 days"):
        await _create(db, name="Too long", to_date=date.today() + timedelta(days=20))


async def test_template_must_carry_the_link(db):
    await _plan(db, monthly=2, days=30)
    with pytest.raises(campaigns.CampaignError, match="{link}"):
        await _create(db, message_template="Please review us")


async def test_duplicate_reuses_copy_but_starts_empty(db):
    await _plan(db, monthly=2, days=30)
    original = await _create(db)
    db.add(ReviewRequest(
        user_id="tenant-campaigns-1", campaign_id=original.id,
        channel="email", status="clicked", clicked_at=datetime.now(timezone.utc),
    ))
    await db.commit()
    await campaigns.refresh_results(db, "tenant-campaigns-1", original.id)
    assert original.clicked_count == 1

    copy = await campaigns.duplicate_campaign(db, "tenant-campaigns-1", original.id)
    assert copy.duplicated_from == original.id
    assert copy.message_template == original.message_template
    assert copy.clicked_count == 0
    assert (copy.to_date - copy.from_date) == (original.to_date - original.from_date)


async def test_cancel_and_results(db):
    await _plan(db, monthly=2, days=30)
    row = await _create(db)
    cancelled = await campaigns.cancel_campaign(db, "tenant-campaigns-1", row.id)
    assert cancelled.status == "cancelled"
    assert campaigns.campaign_status(cancelled) == "cancelled"
    listed = await campaigns.list_campaigns(db, "tenant-campaigns-1")
    assert listed[0]["status"] == "cancelled"


# -- HTTP surface -------------------------------------------------------------

async def _seed_endpoint_plan(db, user_id):
    from app.modules.billing.models import Plan, TenantSubscription

    plan = Plan(
        id="plan-campaign-endpoint", slug="campaign-endpoint", name="Campaign Plan",
        max_campaigns_per_month=3, max_campaign_days=14,
        features={"reviews": True}, is_active=True, sort_order=98,
    )
    db.add(plan)
    await db.commit()
    db.add(TenantSubscription(tenant_id=user_id, plan_id=plan.id, status="active"))
    await db.commit()


@pytest.mark.asyncio
async def test_campaign_endpoints(client, db, user_id):
    await _seed_endpoint_plan(db, user_id)
    start = (date.today() + timedelta(days=1)).isoformat()
    end = (date.today() + timedelta(days=3)).isoformat()
    created = client.post("/api/v1/analytics/campaigns", json={
        "name": "HTTP campaign", "from_date": start, "to_date": end,
        "message_template": "Hi {name} - {link}",
    })
    assert created.status_code == 201, created.text
    campaign_id = created.json()["id"]

    listed = client.get("/api/v1/analytics/campaigns")
    assert listed.status_code == 200
    assert any(c["id"] == campaign_id for c in listed.json())

    duplicated = client.post(f"/api/v1/analytics/campaigns/{campaign_id}/duplicate")
    assert duplicated.status_code == 201
    assert duplicated.json()["duplicated_from"] == campaign_id

    cancelled = client.post(f"/api/v1/analytics/campaigns/{campaign_id}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_campaign_endpoint_rejects_bad_template(client, db, user_id):
    await _seed_endpoint_plan(db, user_id)
    start = (date.today() + timedelta(days=1)).isoformat()
    end = (date.today() + timedelta(days=3)).isoformat()
    response = client.post("/api/v1/analytics/campaigns", json={
        "name": "Bad", "from_date": start, "to_date": end,
        "message_template": "No link here",
    })
    assert response.status_code == 422

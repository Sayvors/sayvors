"""Bulk review-request email is capped per tenant, independently of WhatsApp.

The shared Resend domain must survive one runaway campaign. The cap is counted
at enqueue time so scheduled rows cannot exceed it later.
"""
from datetime import datetime, timezone

import pytest

from app.config import settings
from app.modules.analytics.models import ReviewCampaign, ReviewRequest


async def _seed_emails(db, user_id: str, count: int) -> None:
    now = datetime.now(timezone.utc)
    for i in range(count):
        db.add(
            ReviewRequest(
                id=f"email-seed-{i}",
                user_id=user_id,
                contact=f"seed{i}@example.com",
                channel="email",
                trigger="campaign",
                status="sent",
                sent_at=now,
            )
        )
    await db.commit()


async def _seed_active_campaign(db, user_id: str) -> ReviewCampaign:
    today = datetime.now(timezone.utc).date()
    row = ReviewCampaign(
        tenant_id=user_id,
        name="Email quota campaign",
        from_date=today,
        to_date=today,
        status="active",
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def test_bulk_email_queues_only_the_remaining_headroom(
    client, db, user_id, monkeypatch
):
    monkeypatch.setattr(settings, "BULK_EMAIL_DAILY_LIMIT", 2)
    await _seed_emails(db, user_id, 1)
    await _seed_active_campaign(db, user_id)

    response = client.post(
        "/api/v1/analytics/review-requests/bulk",
        json={
            "channel": "email",
            "contacts": [
                {"email": "a@example.com"},
                {"email": "b@example.com"},
                {"email": "c@example.com"},
            ],
            "mode": "now",
            "trigger": "campaign",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["queued"] == 1
    assert body["skipped_quota"] == 2
    assert body["quota"] == {
        "used": 1,
        "max": 2,
        "remaining": 1,
        "requested": 3,
        "window": "24h",
    }


async def test_single_email_delivery_is_blocked_at_the_cap(
    client, db, user_id, monkeypatch
):
    monkeypatch.setattr(settings, "BULK_EMAIL_DAILY_LIMIT", 2)
    await _seed_emails(db, user_id, 2)

    response = client.post(
        "/api/v1/analytics/review-requests",
        json={
            "channel": "email",
            "contact": "one-more@example.com",
            "deliver": True,
        },
    )

    assert response.status_code == 429
    assert "Daily email limit reached" in response.json()["detail"]


async def test_whatsapp_bulk_ignores_the_email_cap(client, db, user_id, monkeypatch):
    """The email ceiling must not leak into the plan's WhatsApp allowance."""
    monkeypatch.setattr(settings, "BULK_EMAIL_DAILY_LIMIT", 0)
    await _seed_active_campaign(db, user_id)

    response = client.post(
        "/api/v1/analytics/review-requests/bulk",
        json={
            "channel": "whatsapp",
            "contacts": [{"phone": "+966500000001"}],
            "mode": "now",
            "trigger": "campaign",
        },
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["queued"] == 1
    assert body["skipped_quota"] == 0
    assert body["quota"]["window"] == "month"

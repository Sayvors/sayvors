"""Customers page: SQL filtering, pagination, RBAC and batched augmentation."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.modules.analytics.models import ReviewInsight
from app.modules.channels import customers_service
from app.modules.channels.models import (
    Channel,
    ChannelMessage,
    ChannelThread,
    Lead,
    ReviewReply,
)
from app.modules.channels.service import (
    encrypt_contact_phone,
    encrypt_message_content,
    hash_contact_phone,
)

URL = "/api/v1/customers"


async def _channel(db, user_id, cid, platform="whatsapp", name="Line", asset="pn-1"):
    db.add(
        Channel(
            id=cid,
            user_id=user_id,
            platform=platform,
            platform_user_id=asset,
            display_name=name,
            status="active",
        )
    )
    await db.commit()


async def _msg(
    db,
    channel_id,
    phone,
    content="hi",
    minutes_ago=0,
    platform_message_id=None,
):
    db.add(
        ChannelMessage(
            id=f"m-{abs(hash((channel_id, phone, content, minutes_ago))) % 10**12}",
            channel_id=channel_id,
            platform_message_id=platform_message_id,
            direction="inbound",
            content=encrypt_message_content(content),
            content_type="text",
            status="delivered",
            contact_phone=encrypt_contact_phone(phone),
            contact_phone_hash=hash_contact_phone(phone) if phone else None,
            created_at=datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
        )
    )
    await db.commit()


async def _thread(db, channel_id, phone, **fields):
    row = (
        await db.execute(
            select(ChannelThread).where(
                ChannelThread.channel_id == channel_id,
                ChannelThread.contact_phone_hash == hash_contact_phone(phone),
            )
        )
    ).scalar_one()
    for key, value in fields.items():
        setattr(row, key, value)
    await db.commit()


async def _seed(db, user_id):
    await _channel(db, user_id, "chan-1", name="WhatsApp")
    for i, minutes in enumerate((30, 20, 10), start=1):
        await _msg(
            db, "chan-1", f"96650000000{i}", f"message {i}", minutes_ago=minutes
        )
    await _thread(db, "chan-1", "966500000001", category="complaint", priority="urgent")
    await _thread(db, "chan-1", "966500000002", category="normal", priority="high")
    await _thread(db, "chan-1", "966500000003", category="normal", priority="normal")

    db.add(
        Lead(
            id="lead-1",
            tenant_id=user_id,
            channel_id="chan-1",
            platform="whatsapp",
            contact_id="966500000001",
            contact_name="Customer One",
            stage="qualified",
            category="retail",
            intent="buying",
        )
    )
    await db.commit()

    await _channel(
        db,
        user_id,
        "chan-google",
        platform="google_reviews",
        name="Google",
        asset="loc-1",
    )
    await _msg(
        db,
        "chan-google",
        "google:reviewer1",
        "great place",
        minutes_ago=40,
        platform_message_id="review-1",
    )
    db.add(
        ReviewReply(
            id="reply-1",
            channel_id="chan-google",
            review_id="review-1",
            rating=5,
            review_text="great place",
            reply_text="Thank you!",
            status="posted",
        )
    )
    db.add(
        ReviewInsight(
            id="insight-1",
            user_id=user_id,
            channel_id="chan-google",
            review_id="review-1",
            rating=5,
            review_text="great place",
            reviewer_name="Hamza Shah",
            reviewer_photo_url="https://lh3.googleusercontent.com/avatar",
        )
    )
    await db.commit()


@pytest.mark.asyncio
async def test_customers_page_filters_sorts_and_paginates_in_sql(client, db, user_id):
    await _seed(db, user_id)

    first = client.get(URL, params={"limit": 2, "sort": "recent"})
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["total"] == 4
    assert [c["contact_phone"] for c in body["customers"]] == [
        "966500000003",
        "966500000002",
    ]
    cursor = body["next_cursor"]
    assert cursor

    second = client.get(
        URL, params={"limit": 2, "sort": "recent", "cursor": cursor}
    )
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["total"] == 4
    assert {c["contact_phone"] for c in body["customers"]} == {
        "966500000001",
        "google:reviewer1",
    }
    assert body["next_cursor"] is None


@pytest.mark.asyncio
async def test_customers_page_important_sort_and_filters(client, db, user_id):
    await _seed(db, user_id)

    important = client.get(URL, params={"sort": "important"}).json()
    assert important["total"] == 4
    assert [c["important"] for c in important["customers"][:2]] == [True, True]

    filtered = client.get(URL, params={"important": "true"}).json()
    assert filtered["total"] == 2
    assert all(c["important"] for c in filtered["customers"])

    complaint = client.get(URL, params={"category": "complaint"}).json()
    assert complaint["total"] == 1
    assert complaint["customers"][0]["contact_phone"] == "966500000001"

    google = client.get(URL, params={"platform": "google_reviews"}).json()
    assert google["total"] == 1
    row = google["customers"][0]
    assert row["contact_phone"] == "google:reviewer1"
    assert row["display_name"] == "Hamza Shah"
    assert row["avatar_url"] == "https://lh3.googleusercontent.com/avatar"
    assert row["has_review"] is True


@pytest.mark.asyncio
async def test_google_customer_profile_resolves_reviewer_identity(client, db, user_id):
    await _seed(db, user_id)

    r = client.get(f"{URL}/chan-google/google:reviewer1")
    assert r.status_code == 200, r.text
    identity = r.json()["identity"]
    assert identity["name"] == "Hamza Shah"
    assert identity["avatar_url"] == "https://lh3.googleusercontent.com/avatar"
    assert identity["platform"] == "google_reviews"
    assert r.json()["reviews"][0]["reply_text"] == "Thank you!"


@pytest.mark.asyncio
async def test_customers_page_augments_leads_without_n_plus_one(
    client, db, user_id, monkeypatch
):
    await _seed(db, user_id)

    async def _must_not_be_called(*args, **kwargs):
        raise AssertionError("list path must batch review lookups")

    monkeypatch.setattr(customers_service, "_reviews_for", _must_not_be_called)

    row = next(
        c
        for c in client.get(URL, params={"limit": 10}).json()["customers"]
        if c["contact_phone"] == "966500000001"
    )
    assert row["lead_stage"] == "qualified"
    assert row["lead_category"] == "retail"
    assert row["intent"] == "buying"


@pytest.mark.asyncio
async def test_customers_page_applies_rbac_before_pagination(db, user_id):
    await _channel(db, user_id, "chan-rbac-1", name="One")
    await _channel(db, user_id, "chan-rbac-2", name="Two")
    await _msg(db, "chan-rbac-1", "966500000101", "one", minutes_ago=10)
    await _msg(db, "chan-rbac-2", "966500000102", "two", minutes_ago=5)
    await db.commit()

    rows, total, next_cursor = await customers_service.list_customers(
        db,
        SimpleNamespace(id=user_id),
        limit=1,
        visible_channel_ids={"chan-rbac-1"},
    )

    assert total == 1
    assert [r["channel_id"] for r in rows] == ["chan-rbac-1"]
    assert next_cursor is None

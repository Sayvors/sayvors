"""Growth cards: review-request funnel, contacts, ask timing, actions."""
from datetime import datetime, timedelta, timezone

import pytest

from app.modules.analytics.growth_cards import get_growth_cards
from app.modules.analytics.models import ChannelDailyMetric, ReviewInsight, ReviewRequest
from app.modules.channels.models import Channel


async def _seed(db, user_id):
    db.add(Channel(
        id="ch-g", user_id=user_id, platform="whatsapp",
        platform_user_id="acct-g", display_name="Growth", status="active", metadata_json="{}",
    ))
    now = datetime.now(timezone.utc)
    # 10 requests: 6 delivered, 3 clicked, 1 reviewed.
    for i in range(10):
        status = "sent"
        if i < 6:
            status = "delivered"
        if i < 3:
            status = "clicked"
        if i == 0:
            status = "reviewed"
        db.add(ReviewRequest(
            id=f"req-{i}", user_id=user_id, channel_id="ch-g", contact=f"+96650000000{i}",
            channel="whatsapp" if i < 7 else "email",
            trigger="qr" if i < 4 else "manual",
            status=status,
            sent_via="sms" if i < 6 else "email",
            sent_at=now - timedelta(days=3),
            clicked_at=(now - timedelta(days=2)) if status in ("clicked", "reviewed") else None,
        ))
    # 2 reviews in the window.
    for i, rating in enumerate((5, 4)):
        db.add(ReviewInsight(
            id=f"rev-{i}", user_id=user_id, channel_id="ch-g", review_id=f"rid-{i}",
            rating=rating, review_text="good", reviewer_name=f"Guest {i}",
            sentiment="positive", sentiment_score=0.8, topics=[], products=[], problems=[],
            enrichment_status="done", replied=(i == 0),
            review_updated_at=now - timedelta(days=1),
        ))
    db.add(ChannelDailyMetric(
        id="cdm-g", user_id=user_id, channel_id="ch-g", date=now.date(),
        messages_in=5, messages_out=4, conversations_in=3, conversations_replied=2,
        contacts_new=8,
    ))
    await db.commit()


@pytest.mark.asyncio
async def test_growth_cards_funnel_and_contacts(db, user_id):
    await _seed(db, user_id)
    out = await get_growth_cards(db, user_id, None, 30)

    f = out["funnel"]
    assert f["requests_sent"] == 10
    assert f["delivered"] == 10
    assert f["clicked"] == 3
    assert f["reviews"] == 2
    # Two reviews, three clicks: each review is credited to a distinct click.
    assert f["reviews_via_request"] == 2
    assert f["conversion_rate"] == 20.0
    assert f["attribution_window_days"] == 7
    assert f["avg_rating"] == 4.5
    assert f["delivery_tracked"] is True
    assert f["click_tracked"] is True
    assert {c["channel"] for c in f["by_channel"]} == {"whatsapp", "email"}
    assert {t["trigger"] for t in f["by_trigger"]} == {"qr", "manual"}

    contacts = out["contacts"]
    assert contacts["new_contacts"] == 8
    assert contacts["by_platform"] == [{"platform": "whatsapp", "contacts": 8}]
    assert contacts["attribution"] == "unknown"

    assert out["retention"]["available"] is False
    assert any(a["kind"] == "reply" for a in out["actions"])


@pytest.mark.asyncio
async def test_growth_cards_empty_tenant(db, user_id):
    out = await get_growth_cards(db, user_id, None, 30)
    assert out["funnel"]["requests_sent"] == 0
    assert out["funnel"]["conversion_rate"] is None
    assert out["contacts"]["new_contacts"] == 0
    kinds = {a["kind"] for a in out["actions"]}
    assert "connect" in kinds

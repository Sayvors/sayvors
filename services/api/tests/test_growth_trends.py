"""Growth trends + search keywords (no network, sqlite DB)."""
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.modules.analytics import performance
from app.modules.analytics.models import LocationDailyMetric, SearchKeywordStat


def _day(n: int) -> date:
    from datetime import datetime, timezone

    return (datetime.now(timezone.utc) - timedelta(days=n)).date()


def test_fetch_day_parses_listing_row(monkeypatch):
    from integrations.channels import embedsocial

    monkeypatch.setattr(
        embedsocial,
        "fetch_listing_metrics",
        lambda start, end, listing_id=None, **kw: {
            "listings": [{
                "googleMapsDesktop": 10, "googleMapsMobile": 20,
                "googleSearchDesktop": 5, "googleSearchMobile": 7,
                "websiteClicks": 3, "callClicks": 2, "directions": 1,
                "messages": 4, "bookings": 0,
            }]
        },
    )
    nums = embedsocial.fetch_listing_metrics_for_day("loc-1", _day(1))
    assert nums["impressions_maps_desktop"] == 10
    assert nums["impressions_maps_mobile"] == 20
    assert nums["impressions_search"] == 12
    assert nums["website_clicks"] == 3
    assert nums["direction_requests"] == 1


def test_fetch_day_empty_payload_is_zeros(monkeypatch):
    from integrations.channels import embedsocial

    monkeypatch.setattr(
        embedsocial, "fetch_listing_metrics",
        lambda start, end, listing_id=None, **kw: {},
    )
    nums = embedsocial.fetch_listing_metrics_for_day("loc-1", _day(1))
    assert sum(nums.values()) == 0


def test_fetch_day_api_error_is_zeros(monkeypatch):
    from integrations.channels import embedsocial

    def _boom(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(embedsocial, "fetch_listing_metrics", _boom)
    assert sum(embedsocial.fetch_listing_metrics_for_day("loc-1", _day(1)).values()) == 0


@pytest.mark.asyncio
async def test_localith_upsert_writes_same_table(db, user_id, channel_id):
    from sqlalchemy import select as _select

    from app.modules.channels.models import Channel

    channel = (await db.execute(
        _select(Channel).where(Channel.id == channel_id)
    )).scalar_one()
    await performance._upsert_localith_day(db, channel, _day(2), {
        "impressions_maps_desktop": 11, "impressions_maps_mobile": 22,
        "impressions_search": 5, "website_clicks": 3, "call_clicks": 1,
        "direction_requests": 2, "messages": 0, "bookings": 0,
    })
    await db.commit()
    row = (await db.execute(
        _select(LocationDailyMetric).where(
            LocationDailyMetric.channel_id == channel_id)
    )).scalar_one()
    assert row.impressions_maps_desktop == 11
    assert row.extra["source"] == "localith"
    assert row.extra["impressions_search"] == 5
    # Idempotent re-upsert overwrites, never twins.
    await performance._upsert_localith_day(db, channel, _day(2), {
        "impressions_maps_desktop": 99, "impressions_maps_mobile": 0,
        "impressions_search": 0, "website_clicks": 0, "call_clicks": 0,
        "direction_requests": 0, "messages": 0, "bookings": 0,
    })
    await db.commit()
    rows = (await db.execute(
        _select(LocationDailyMetric).where(LocationDailyMetric.channel_id == channel_id)
    )).scalars().all()
    assert len(rows) == 1
    assert rows[0].impressions_maps_desktop == 99


@pytest.mark.asyncio
async def test_keywords_unavailable_without_native_channel(db, user_id, channel_id):
    """Fixture channel has no OAuth tokens → honest empty state."""
    from app.modules.analytics import growth

    out = await growth.get_keywords(db, user_id, None, 30)
    assert out["available"] is False
    assert out["keywords"] == []


@pytest.mark.asyncio
async def test_keywords_served_with_trend(db, user_id, channel_id):
    from sqlalchemy import select as _select

    from app.modules.analytics import growth
    from app.modules.channels.models import Channel

    ch = (await db.execute(
        _select(Channel).where(Channel.id == channel_id)
    )).scalar_one()
    ch.access_token = "tok"
    # 60 vs 20 impressions → +200%.
    db.add(SearchKeywordStat(user_id=user_id, channel_id=channel_id,
                             keyword="shawarma near me", date=_day(5), impressions=60))
    db.add(SearchKeywordStat(user_id=user_id, channel_id=channel_id,
                             keyword="shawarma near me", date=_day(40), impressions=20))
    db.add(SearchKeywordStat(user_id=user_id, channel_id=channel_id,
                             keyword="burger", date=_day(3), impressions=10))
    await db.commit()

    out = await growth.get_keywords(db, user_id, None, 30)
    assert out["available"] is True
    by_kw = {k["keyword"]: k for k in out["keywords"]}
    assert by_kw["shawarma near me"]["impressions"] == 60
    assert by_kw["shawarma near me"]["trend_pct"] == 200.0
    assert by_kw["burger"]["impressions"] == 10
    assert by_kw["burger"]["trend_pct"] is None  # no prior window → honest null
    # Ranked by impressions desc.
    assert out["keywords"][0]["keyword"] == "shawarma near me"


@pytest.mark.asyncio
async def test_keywords_endpoint_shape(client, db, user_id, channel_id):
    r = client.get("/api/v1/analytics/growth/keywords?days=30",
                   headers={"host": "localhost"})
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) >= {"days", "available", "keywords"}

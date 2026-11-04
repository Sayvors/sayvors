"""Growth trends + search keywords (no network, sqlite DB)."""
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.modules.analytics.models import SearchKeywordStat


def _day(n: int) -> date:
    from datetime import datetime, timezone

    return (datetime.now(timezone.utc) - timedelta(days=n)).date()


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

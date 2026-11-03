"""Google Business Profile Performance API request/parse shapes."""
from datetime import datetime, timezone

import pytest

from app.modules.channels.google_reviews import GoogleReviewsClient


class _Resp:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code
        self.text = ""

    def json(self) -> dict:
        return self._payload


@pytest.mark.asyncio
async def test_performance_uses_get_and_parses_nested_series():
    client = GoogleReviewsClient("token")
    captured: dict = {}

    async def _fake(method: str, url: str, **kwargs):
        captured["method"] = method
        captured["url"] = url
        captured["params"] = kwargs.get("params") or []
        return _Resp({
            "multiDailyMetricTimeSeries": [{
                "dailyMetricTimeSeries": [
                    {
                        "dailyMetric": "WEBSITE_CLICKS",
                        "timeSeries": {"datedValues": [
                            {"date": {"year": 2026, "month": 11, "day": 1}, "value": "3"},
                            {"date": {"year": 2026, "month": 11, "day": 2}},
                        ]},
                    },
                    {
                        "dailyMetric": "BUSINESS_IMPRESSIONS_DESKTOP_MAPS",
                        "timeSeries": {"datedValues": [
                            {"date": {"year": 2026, "month": 11, "day": 1}, "value": "7"},
                        ]},
                    },
                ],
            }],
        })

    client._authed_request = _fake
    start = datetime(2026, 11, 1, tzinfo=timezone.utc)
    end = datetime(2026, 11, 2, tzinfo=timezone.utc)
    out = await client.fetch_performance_timeseries("loc-1", start, end)
    await client.close()

    assert captured["method"] == "GET"
    assert captured["url"].endswith("/locations/loc-1:fetchMultiDailyMetricsTimeSeries")
    assert ("dailyMetrics", "BUSINESS_DIRECTION_REQUESTS") in captured["params"]
    assert ("dailyMetrics", "DIRECTION_REQUESTS") not in captured["params"]
    assert out["WEBSITE_CLICKS"] == [(start.date(), 3)]
    assert out["BUSINESS_IMPRESSIONS_DESKTOP_MAPS"] == [(start.date(), 7)]


@pytest.mark.asyncio
async def test_keywords_use_monthly_endpoint_and_drop_thresholds():
    client = GoogleReviewsClient("token")
    captured: dict = {}

    async def _fake(method: str, url: str, **kwargs):
        captured["method"] = method
        captured["url"] = url
        return _Resp({
            "searchKeywordsCounts": [
                {"searchKeyword": "coffee", "insightsValue": {"value": "21"}},
                {"searchKeyword": "quiet cafe", "insightsValue": {"threshold": "15"}},
            ],
        })

    client._authed_request = _fake
    start = datetime(2026, 10, 15, tzinfo=timezone.utc)
    end = datetime(2026, 11, 2, tzinfo=timezone.utc)
    out = await client.fetch_keyword_timeseries("loc-1", start, end)
    await client.close()

    assert captured["method"] == "GET"
    assert captured["url"].endswith("/locations/loc-1/searchkeywords/impressions/monthly")
    # Trailing six months, stored on the first of each month; threshold-only
    # rows are omitted.
    coffee = out["coffee"]
    assert len(coffee) == 7
    assert coffee[0] == (datetime(2026, 5, 1).date(), 21)
    assert coffee[-1] == (datetime(2026, 11, 1).date(), 21)
    assert "quiet cafe" not in out

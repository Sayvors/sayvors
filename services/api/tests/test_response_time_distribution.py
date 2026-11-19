"""FACT-8: a median and distribution, because one slow reply skews the average."""
from datetime import datetime, timedelta, timezone

import pytest

from app.modules.analytics.service import (
    RESPONSE_SAMPLE_LIMIT,
    _response_distribution,
)


def test_median_ignores_outliers_that_dominate_the_average():
    # Nine replies in 10 minutes, one after 10 hours. Average ≈ 1h, but the
    # typical reply is 10 minutes — the number a merchant should see.
    values = [600.0] * 8 + [36000.0, 36000.0]
    result = _response_distribution(values)
    assert result["sample_size"] == 10
    assert result["median_seconds"] == 600
    assert result["p90_seconds"] == 36000
    assert result["truncated"] is False


def test_buckets_are_exhaustive_and_non_overlapping():
    values = [60.0, 7200.0, 200000.0, 700000.0]
    result = _response_distribution(values)
    buckets = result["buckets"]
    assert [b["key"] for b in buckets] == [
        "under_1h", "1h_to_24h", "1d_to_7d", "over_7d"
    ]
    assert sum(b["count"] for b in buckets) == 4
    assert round(sum(b["pct"] for b in buckets)) == 100


def test_empty_and_negative_samples_are_honest():
    empty = _response_distribution([])
    assert empty["sample_size"] == 0
    assert empty["median_seconds"] is None and empty["buckets"] == []
    # A reply recorded before the review's update time is a clock artefact,
    # not a negative response time.
    clamped = _response_distribution([-50.0, 100.0])
    assert clamped["median_seconds"] == 50
    assert all(b["count"] >= 0 for b in clamped["buckets"])


def test_truncated_flag_at_the_sample_cap():
    values = [10.0] * RESPONSE_SAMPLE_LIMIT
    assert _response_distribution(values)["truncated"] is True


@pytest.mark.asyncio
async def test_overview_exposes_response_time(db, user_id):
    """The overview response carries the new block alongside the old average."""
    from app.modules.analytics.service import get_overview

    overview = await get_overview(db, user_id, None, 30)
    assert "response_time" in overview
    block = overview["response_time"]
    assert block["sample_size"] >= 0
    assert isinstance(block["buckets"], list)
    if block["buckets"]:
        assert set(block["buckets"][0]) == {"key", "count", "pct"}

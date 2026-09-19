"""Intelligence aggregation unit tests (pure functions)."""
from datetime import datetime, timedelta, timezone

from app.modules.analytics.intelligence import (
    _agg_entities,
    _is_emerging,
    _period_bounds,
    _trend,
)
from app.modules.analytics.growth import _delta
from app.modules.analytics.service import health_score, reputation_score


def test_trend_percent_change():
    assert _trend(15, 10) == 50.0
    assert _trend(5, 10) == -50.0
    assert _trend(10, 10) == 0.0
    assert _trend(10, 0) is None


def test_is_emerging_threshold():
    assert _is_emerging(3, 0) is True
    assert _is_emerging(2, 0) is False
    assert _is_emerging(5, 3) is False


def test_period_bounds_equal_length():
    now = datetime.now(timezone.utc)
    cur_start, cur_end, prev_start, prev_end = _period_bounds(30)
    assert cur_end == now
    assert cur_start == now - timedelta(days=30)
    assert prev_start == now - timedelta(days=60)
    assert prev_end == cur_start


def test_agg_entities_counts_sentiment():
    rows = [
        ("positive", 5, [{"name": "service", "sentiment": "positive"}], [], []),
        ("negative", 1, [{"name": "service", "sentiment": "negative"}], [], []),
        ("neutral", 3, [{"name": "service", "sentiment": "neutral"}], [], []),
    ]
    agg = _agg_entities(rows, "topics")
    assert agg["service"]["mentions"] == 3
    assert agg["service"]["positive"] == 1
    assert agg["service"]["negative"] == 1
    assert agg["service"]["neutral"] == 1


def test_agg_entities_problems_severity():
    rows = [
        ("negative", 1, [], [], [{"name": "slow service", "severity": "high"}]),
        ("negative", 1, [], [], [{"name": "slow service", "severity": "medium"}]),
    ]
    agg = _agg_entities(rows, "problems")
    assert agg["slow service"]["mentions"] == 2
    assert agg["slow service"]["severity"]["high"] == 1
    assert agg["slow service"]["severity"]["medium"] == 1


def test_reputation_score_range():
    assert reputation_score(5.0, 1.0, 1.0) == 100
    assert reputation_score(0.0, 0.0, 0.0) == 0
    assert 0 <= reputation_score(4.0, 0.8, 0.7) <= 100


def test_health_score_uses_momentum():
    assert health_score(5.0, 1.0, 1.0, 2.0) == 100  # max rating + full momentum
    assert 0 <= health_score(3.0, 0.5, 0.5, 1.0) <= 100


def test_growth_delta():
    assert _delta(110, 100) == 10.0
    assert _delta(90, 100) == -10.0
    assert _delta(10, 0) is None
    assert _delta(0, 0) is None
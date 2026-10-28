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
    # _period_bounds() takes its own `now`, so these differ by microseconds.
    # What matters is that the window is exactly 30 days and the two windows
    # meet without a gap or an overlap.
    assert abs((cur_end - now).total_seconds()) < 0.01
    assert abs((cur_start - (cur_end - timedelta(days=30))).total_seconds()) < 0.01
    assert abs((prev_end - prev_start).total_seconds() - 30 * 86400) < 0.01
    assert prev_end == cur_start


def test_agg_entities_counts_sentiment():
    rows = [
        ("positive", 5, [{"name": "service", "sentiment": "positive"}], [], [], None, "ch-1"),
        ("negative", 1, [{"name": "service", "sentiment": "negative"}], [], [], None, "ch-1"),
        ("neutral", 3, [{"name": "service", "sentiment": "neutral"}], [], [], None, "ch-1"),
    ]
    agg = _agg_entities(rows, "topics")
    assert agg["service"]["mentions"] == 3
    assert agg["service"]["positive"] == 1
    assert agg["service"]["negative"] == 1
    assert agg["service"]["neutral"] == 1


def test_agg_entities_problems_severity():
    rows = [
        ("negative", 1, [], [], [{"name": "slow service", "severity": "high"}], {"entities": {"staff": ["Sara"]}}, "ch-1"),
        ("negative", 1, [], [], [{"name": "slow service", "severity": "medium"}], None, "ch-1"),
    ]
    agg = _agg_entities(rows, "problems")
    assert agg["slow service"]["mentions"] == 2
    assert agg["slow service"]["severity"]["high"] == 1
    assert agg["slow service"]["severity"]["medium"] == 1
    # Meaning layer: staff named on one review; high severity counts as serious.
    assert agg["slow service"]["staff_named"] == 1
    assert agg["slow service"]["serious"] == 1


def test_canonical_complaint_areas():
    from app.modules.analytics.intelligence import _canonical_complaint

    assert _canonical_complaint("long waiting time") == "waiting_time"
    assert _canonical_complaint("rude staff") == "staff_service"
    assert _canonical_complaint("wrong order") == "order_accuracy"
    assert _canonical_complaint("dirty tables") == "cleanliness"
    assert _canonical_complaint("too expensive") == "price_value"
    assert _canonical_complaint("cold food") == "quality"
    assert _canonical_complaint("parking") == "other"


def test_agg_areas_rolls_terms_and_trends():
    from app.modules.analytics.intelligence import _agg_areas

    cur = {
        "long waiting time": {"mentions": 3, "staff_named": 0, "serious": 1},
        "rude staff": {"mentions": 2, "staff_named": 1, "serious": 0},
    }
    prev = {"long waiting time": {"mentions": 1, "staff_named": 0, "serious": 0}}
    areas = _agg_areas(cur, prev)
    by_cat = {a["category"]: a for a in areas}
    assert by_cat["waiting_time"]["mentions"] == 3
    assert by_cat["waiting_time"]["trend_pct"] == 200.0
    assert by_cat["waiting_time"]["status"] == "increasing"
    assert by_cat["staff_service"]["staff_named"] == 1


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
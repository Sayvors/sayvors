"""Unit tests for benchmark summary/distribution helpers (pure, no DB)."""
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from app.modules.benchmark.summary import distribution, north_star


def _subject(key, name, *, avg=None, month=None, total=None, pos=None,
             five=None, year=None, kind="saved", available=True):
    return {
        "key": key, "kind": kind, "id": key.split(":", 1)[-1],
        "available": available, "name": name,
        "metrics": {
            "avg_rating": avg, "reviews_last_month": month,
            "reviews_last_year": year, "total_reviews": total,
            "total_ratings": total, "five_star": five,
        },
        "facts": {"positive_pct": pos, "top_problems": []},
    }


def test_distribution_best_median_worst_and_gap():
    rows = distribution([
        _subject("saved:a", "Alpha", avg=4.8, month=12, total=200, pos=90),
        _subject("saved:b", "Beta", avg=4.0, month=6, total=100, pos=70),
        _subject("saved:c", "Gamma", avg=3.2, month=2, total=40, pos=40),
    ])
    rating = rows["avg_rating"]
    assert rating["best"]["name"] == "Alpha" and rating["best"]["value"] == 4.8
    assert rating["median"] == 4.0
    assert rating["worst"]["name"] == "Gamma" and rating["worst"]["value"] == 3.2
    assert rating["gap"] == 1.6
    sentiment = rows["positive_pct"]
    assert sentiment["best"]["value"] == 90
    assert sentiment["median"] == 70
    assert sentiment["gap"] == 50


def test_distribution_skips_unavailable_and_null_metrics():
    rows = distribution([
        _subject("saved:a", "Alpha", avg=4.5, month=10),
        _subject("saved:x", "Dead", available=False, avg=None),
        _subject("saved:b", "Beta", avg=None, month=4),  # avg missing → excluded
    ])
    assert set(rows["avg_rating"]["values"]) == {4.5}
    assert rows["avg_rating"]["gap"] == 0
    assert "positive_pct" not in rows  # no subject carried it


def test_velocity_uses_month_then_year_fallback():
    rows = distribution([
        _subject("saved:a", "Alpha", month=None, year=120, avg=4.0),
        _subject("saved:b", "Beta", month=6, avg=4.0),
    ])
    assert rows["reviews_per_month"]["best"]["value"] == 10  # 120 / 12


def test_north_star_ranks_own_subject_with_gaps():
    out = north_star(
        [
            _subject("saved:a", "Alpha", avg=4.9, month=20, pos=95),
            _subject("own:c1", "Mine", avg=4.2, month=5, pos=60, kind="own"),
            _subject("saved:b", "Beta", avg=3.8, month=9, pos=80),
        ],
        own_keys=["own:c1"],
    )
    assert out["rank"] == 2 and out["of"] == 3
    assert out["leader"]["name"] == "Alpha"
    assert out["gaps"]["avg_rating"] == 0.7
    assert out["gaps"]["reviews_per_month"] == 15
    assert out["gaps"]["positive_pct"] == 35  # leader 95 − own 60
    assert out["health"] == "warn"


def test_north_star_none_without_own_subject():
    assert north_star([_subject("saved:a", "Alpha", avg=4.0)], own_keys=[]) is None


def test_north_star_skips_unavailable_own_subject():
    rows = [
        _subject("saved:a", "Alpha", avg=4.0),
        _subject("own:c1", "Mine", kind="own", available=False),
    ]
    assert north_star(rows, own_keys=["own:c1"]) is None


def test_north_star_unrated_own_sorts_last_with_null_gap():
    out = north_star(
        [
            _subject("saved:a", "Alpha", avg=4.0),
            _subject("own:c1", "Mine", kind="own"),
        ],
        own_keys=["own:c1"],
    )
    assert out["rank"] == 2 and out["of"] == 2
    assert out["gaps"]["avg_rating"] is None


def test_health_buckets():
    from app.modules.benchmark.summary import health_of
    assert health_of(_subject("s", "A", avg=4.5, pos=85)) == "good"
    assert health_of(_subject("s", "A", avg=3.6, pos=60)) == "warn"
    assert health_of(_subject("s", "A", avg=2.9, pos=30)) == "bad"
    assert health_of(_subject("s", "A", avg=None, pos=85)) == "good"  # sentiment-only
    assert health_of(_subject("s", "A", avg=None, pos=None)) == "warn"  # unknown → not good

"""North-star ranking + metric distribution over compare subjects.

Pure functions over the records ``compare_subjects`` returns — no DB, no
I/O — so the ranking logic stays unit-testable and ``compare.py`` stops
growing. The compare router calls these after loading subjects and attaches
the results to the cached response.
"""
from __future__ import annotations

from statistics import median
from typing import Any

# The four headline metrics the compare page opens with; all are
# higher-is-better (the best/worst ordering below assumes it). ``max``
# powers the distribution bar scaling (None = scale to the observed best).
METRIC_SPECS: dict[str, dict[str, Any]] = {
    "avg_rating": {"max": 5.0},
    "reviews_per_month": {"max": None},
    "total_reviews": {"max": None},
    "positive_pct": {"max": 100.0},
}

# Sentiment lives in `facts`, not `metrics` (see compare._blank_facts).
_FACT_METRICS = frozenset({"positive_pct"})

_HEALTH_BAD_RATING = 3.5
_HEALTH_WARN_RATING = 4.3
_HEALTH_BAD_POSITIVE = 50.0
_HEALTH_WARN_POSITIVE = 75.0


def velocity_per_month(subject: dict[str, Any]) -> float | None:
    """Reviews/month: the 30-day window when present, else year ÷ 12."""
    metrics = subject.get("metrics") or {}
    month = metrics.get("reviews_last_month")
    if month is not None:
        return float(month)
    year = metrics.get("reviews_last_year")
    if year is not None:
        return round(float(year) / 12.0, 1)
    return None


def _value(subject: dict[str, Any], metric: str) -> float | None:
    if metric == "reviews_per_month":
        return velocity_per_month(subject)
    container = "facts" if metric in _FACT_METRICS else "metrics"
    value = (subject.get(container) or {}).get(metric)
    if value is None and metric == "total_reviews":
        value = (subject.get("metrics") or {}).get("total_ratings")
    return float(value) if value is not None else None


def health_of(subject: dict[str, Any]) -> str:
    """good / warn / bad — worst bucket across rating and sentiment."""
    rating = _value(subject, "avg_rating")
    positive = _value(subject, "positive_pct")
    if rating is None and positive is None:
        return "warn"  # unknown is never "good"
    buckets = []
    if rating is not None:
        buckets.append("bad" if rating < _HEALTH_BAD_RATING
                       else "warn" if rating < _HEALTH_WARN_RATING else "good")
    if positive is not None:
        buckets.append("bad" if positive < _HEALTH_BAD_POSITIVE
                       else "warn" if positive < _HEALTH_WARN_POSITIVE else "good")
    order = {"bad": 0, "warn": 1, "good": 2}
    return min(buckets, key=lambda b: order[b])


def distribution(subjects: list[dict[str, Any]]) -> dict[str, Any]:
    """Best/median/worst/gap per headline metric across available subjects.

    Unavailable subjects and null metric values are excluded — a subject that
    has not been scraped yet must not drag the median down. ``gap`` is
    best − worst (0 when a single subject carries the metric).
    """
    out: dict[str, Any] = {}
    for metric in METRIC_SPECS:
        values: list[tuple[float, str]] = []
        for subject in subjects:
            if not subject.get("available"):
                continue
            value = _value(subject, metric)
            if value is None:
                continue
            values.append((value, subject.get("name") or subject.get("key") or ""))
        if not values:
            continue
        best_value, best_name = max(values, key=lambda pair: pair[0])
        worst_value, worst_name = min(values, key=lambda pair: pair[0])
        out[metric] = {
            "best": {"name": best_name, "value": best_value},
            "median": round(median([v for v, _ in values]), 2),
            "worst": {"name": worst_name, "value": worst_value},
            "gap": round(best_value - worst_value, 2),
            "values": sorted({v for v, _ in values}),
            "max_scale": METRIC_SPECS[metric]["max"],
        }
    return out


def north_star(
    subjects: list[dict[str, Any]], own_keys: list[str]
) -> dict[str, Any] | None:
    """Rank the tenant's own location(s) against the saved bench.

    Ranking metric is ``avg_rating`` (Google's ordering users actually see);
    gaps are leader − best own value per metric. Returns ``None`` when the
    comparison has no own subject so the card renders nothing instead of a
    meaningless rank.
    """
    available = [s for s in subjects if s.get("available")]
    own = [s for s in available if s.get("key") in set(own_keys)]
    if not own:
        return None

    def _sort_key(subject: dict[str, Any]) -> tuple[float, float]:
        rating = _value(subject, "avg_rating")
        velocity = _value(subject, "reviews_per_month") or 0.0
        # Unrated subjects sort last rather than crashing the comparison.
        return (rating if rating is not None else -1.0, velocity)

    ranked = sorted(available, key=_sort_key, reverse=True)
    leader = ranked[0]
    best_own = max(own, key=_sort_key)
    rank = ranked.index(best_own) + 1

    gaps: dict[str, float | None] = {}
    for metric in METRIC_SPECS:
        leader_value = _value(leader, metric)
        own_value = _value(best_own, metric)
        if leader_value is None or own_value is None:
            gaps[metric] = None
        else:
            gaps[metric] = round(leader_value - own_value, 2)

    return {
        "rank": rank,
        "of": len(ranked),
        "own": {"key": best_own.get("key"), "name": best_own.get("name")},
        "leader": {"key": leader.get("key"), "name": leader.get("name")},
        "gaps": gaps,
        "health": health_of(best_own),
    }

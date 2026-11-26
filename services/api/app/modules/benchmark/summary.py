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
    metrics = subject.get("metrics") or {}
    if metric == "avg_rating":
        # Own analytics uses 0.0 for an empty location. That is missing
        # evidence, not a zero-star business, and must not poison rank/health.
        value = metrics.get("avg_rating")
        if value is None or float(value) <= 0:
            return None
        return float(value)
    if metric == "positive_pct":
        # Saved subjects derive this from stars; own subjects use classified
        # sentiment. An explicit zero review base means 0% is missing evidence.
        reviews = metrics.get("total_reviews")
        if reviews is not None and float(reviews) <= 0:
            return None
    container = "facts" if metric in _FACT_METRICS else "metrics"
    value = (subject.get(container) or {}).get(metric)
    if value is None and metric == "total_reviews":
        value = metrics.get("total_ratings")
    return float(value) if value is not None else None


def value(subject: dict[str, Any], metric: str) -> float | None:
    """Public seam for cross-module consumers of the metric semantics.

    ``_value`` stays the internal name inside this module; this thin alias
    lets e.g. the AI payload builder read through the exact same rules
    (velocity derivation, sentiment container, total_ratings fallback)
    without touching a private symbol.
    """
    return _value(subject, metric)


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


def pressure_scores(
    subjects: list[dict[str, Any]], own_keys: list[str]
) -> list[dict[str, Any]]:
    """Rank competitors by pressure on the selected own branch.

    Score is a simple explainable blend of proximity and performance gaps.
    Only available non-own subjects are scored. Missing inputs reduce
    confidence; we never invent values.
    """
    own_set = {k.strip() for k in own_keys}
    own = [
        s for s in subjects
        if s.get("available") and (s.get("key") or "").strip() in own_set
    ]
    if not own:
        return []
    anchor = own[0]
    out: list[dict[str, Any]] = []
    for s in subjects:
        if not s.get("available") or (s.get("key") or "").strip() in own_set:
            continue
        loc = s.get("location") or {}
        dist = loc.get("distance_km")
        rating_gap = None
        a_rating = value(anchor, "avg_rating")
        c_rating = value(s, "avg_rating")
        if a_rating is not None and c_rating is not None:
            rating_gap = round(c_rating - a_rating, 2)
        velocity_gap = None
        a_vel = value(anchor, "reviews_per_month")
        c_vel = value(s, "reviews_per_month")
        if a_vel is not None and c_vel is not None:
            velocity_gap = round(c_vel - a_vel, 2)
        sentiment_gap = None
        a_pos = value(anchor, "positive_pct")
        c_pos = value(s, "positive_pct")
        if a_pos is not None and c_pos is not None:
            sentiment_gap = round(c_pos - a_pos, 2)

        # Normalize components to 0..1 where higher means more pressure.
        rating_pressure = max(0.0, min(1.0, (rating_gap or 0.0) / 1.5)) if rating_gap is not None else 0.0
        velocity_pressure = max(0.0, min(1.0, (velocity_gap or 0.0) / 20.0)) if velocity_gap is not None else 0.0
        sentiment_pressure = max(0.0, min(1.0, (sentiment_gap or 0.0) / 30.0)) if sentiment_gap is not None else 0.0
        distance_pressure = 0.0
        if isinstance(dist, (int, float)):
            # <=1km high pressure, >=20km low pressure.
            distance_pressure = max(0.0, min(1.0, (20.0 - float(dist)) / 19.0))

        inputs = [rating_gap is not None, velocity_gap is not None, sentiment_gap is not None, isinstance(dist, (int, float))]
        confidence = round(sum(1 for i in inputs if i) / len(inputs), 2)
        score = round((rating_pressure * 0.35 + velocity_pressure * 0.25 + sentiment_pressure * 0.2 + distance_pressure * 0.2) * 100, 1)
        out.append({
            "key": s.get("key"),
            "name": s.get("name"),
            "score": score,
            "confidence": confidence,
            "distance_km": dist,
            "rating_gap": rating_gap,
            "velocity_gap": velocity_gap,
            "sentiment_gap": sentiment_gap,
        })
    out.sort(key=lambda r: (-r["score"], -(r["confidence"]), r.get("name") or ""))
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
    # Membership is normalized on both sides: keys arrive from stored
    # selections and whitespace must not silently unmatch a location.
    own_set = {k.strip() for k in own_keys}
    own = [s for s in available if (s.get("key") or "").strip() in own_set]
    if not own:
        return None
    # Rating rank only makes sense among businesses that have a rating. An
    # unrated branch gets the scorecard empty state, not a fabricated last place.
    rated_own = [s for s in own if _value(s, "avg_rating") is not None]
    if not rated_own:
        return None
    rated = [s for s in available if _value(s, "avg_rating") is not None]

    def _sort_key(subject: dict[str, Any]) -> tuple[float, float]:
        rating = _value(subject, "avg_rating")
        velocity = _value(subject, "reviews_per_month") or 0.0
        return (rating if rating is not None else -1.0, velocity)

    ranked = sorted(rated, key=_sort_key, reverse=True)
    leader = ranked[0]
    best_own = max(rated_own, key=_sort_key)
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

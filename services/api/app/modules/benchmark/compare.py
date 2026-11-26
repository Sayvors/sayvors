"""Two-sided comparison facts for the benchmark comparison page.

A single bounded request returns everything the page needs for both sides, so
the browser never fans out into a dozen analytics calls. Each side is either a
saved competitor (Google Places, through the field-masked client) or one of the
tenant's own Google locations (Sayvors analytics tables).

Honesty rule: facts Google does not expose for a competitor listing (views,
calls, menu prices, registered staff) come back as null with a note, never as
an invented zero. Repeated review themes are extracted separately by the
versioned theme-analysis pipeline, not by hardcoded domain keyword lists.
"""
from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import datetime, timedelta, timezone
from math import atan2, cos, radians, sin, sqrt
from typing import Any

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..analytics.models import LocationDailyMetric, ReviewInsight
from ..analytics.service import get_overview
from ..analytics.staff_mentions import listing_id_for_channel, staff_summary
from ..channels.models import BusinessService, Channel, VerificationRecord
from . import boq, outscraper, places, service
from .models import BenchmarkSnapshot

logger = logging.getLogger(__name__)

MAX_SUBJECTS = 6
# Newest-first sample of a saved place's reviews for the reviews table.
REVIEW_SAMPLE_LIMIT = 500
# How many reviews each subject returns for the reviews table.
MAX_REVIEWS_PER_SUBJECT = 50
REVIEW_TEXT_MAX = 600
# Period filter on the comparison page. "live" reads Google/analytics now; the
# others ask for the same facts restricted to a window, computed from the
# scraper's snapshot history plus the current live values.
RANGES: dict[str, int | None] = {"live": None, "30d": 30, "90d": 90, "365d": 365}
# Google returns at most 500 reviews per place; keep our own sample the same
# size so both sides of the comparison describe the same kind of evidence.
WINDOW_DAYS = {
    "reviews_last_day": 1,
    "reviews_last_week": 7,
    "reviews_last_month": 30,
    "reviews_last_year": 365,
}
# Cohort tags come from merchant-supplied channel metadata, so they are
# bounded before they reach the comparison page's filter chips.
MAX_TAGS = 5
MAX_TAG_LENGTH = 30

PLACE_TYPE_LABELS = {
    "restaurant": "Restaurant", "cafe": "Cafe", "coffee_shop": "Coffee shop",
    "bakery": "Bakery", "fast_food_restaurant": "Fast food", "bar": "Bar",
    "hotel": "Hotel", "gym": "Gym", "hair_salon": "Hair salon", "spa": "Spa",
    "clothing_store": "Clothing", "store": "Store", "shopping_mall": "Mall",
    "gas_station": "Petrol station", "car_wash": "Car wash", "pharmacy": "Pharmacy",
    "hospital": "Hospital", "dentist": "Dentist", "school": "School",
    "university": "University", "beauty_salon": "Beauty salon",
}


class CompareError(ValueError):
    """A subject that cannot be compared (safe to show on that side only)."""


def parse_subject(raw: str) -> tuple[str, str]:
    """Split ``saved:<place_id>`` or ``own:<channel_id>`` into kind and id.

    Raises CompareError on anything else so a malformed deep link cannot be
    used as a free Places lookup or a cross-tenant channel read.
    """
    value = str(raw or "").strip()
    kind, sep, ident = value.partition(":")
    if not sep or kind not in {"saved", "own"}:
        raise CompareError("Unknown comparison subject.")
    ident = ident.strip()[:255]
    if not ident:
        raise CompareError("Comparison subject is missing an id.")
    return kind, ident


def _blank_metrics() -> dict[str, Any]:
    return {
        "total_reviews": None,
        **{key: None for key in WINDOW_DAYS},
        "avg_rating": None,
        "total_ratings": None,
        "five_star": None,
        "four_star": None,
        "one_star": None,
        "star_share_base": None,
        "impressions": None,
        "calls": None,
        # Period-only facts; null when the filter is "live".
        "period_reviews": None,
        "period_avg_rating": None,
        "rating_change": None,
        "period_impressions": None,
        "period_calls": None,
        # Previous equivalent window for delta/waterfall visuals. Null when unknown.
        "prev_period_reviews": None,
        "prev_period_avg_rating": None,
        "period_reviews_delta": None,
        "period_avg_rating_delta": None,
    }


def _blank_facts() -> dict[str, Any]:
    return {
        "positive_pct": None,
        "negative_pct": None,
        "branch": None,
        "services": [],
        "top_problems": [],
        "named_team": [],
    }


def _channel_tags(channel: Channel) -> list[str]:
    """Cohort tags of an own location, from its channel metadata.

    Metadata is merchant-supplied free-text JSON, so the parse is defensive
    (malformed JSON means no tags, not a failed comparison) and the values are
    normalized before they drive the UI's filter chips: trimmed, lowercased,
    deduplicated preserving first-seen order, capped at MAX_TAGS tags of at
    most MAX_TAG_LENGTH characters. Non-string entries are dropped.
    """
    try:
        meta = json.loads(channel.metadata_json or "{}")
    except (json.JSONDecodeError, TypeError):
        return []
    raw = meta.get("tags") if isinstance(meta, dict) else None
    if not isinstance(raw, list):
        return []
    tags = []
    for item in raw:
        if not isinstance(item, str):
            continue
        tag = item.strip().lower()[:MAX_TAG_LENGTH]
        if tag:
            tags.append(tag)
    return list(dict.fromkeys(tags))[:MAX_TAGS]


def _haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in km. Pure and cheap; used for market proximity."""
    r = 6371.0
    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    return 2 * r * atan2(sqrt(a), sqrt(1 - a))


def _subject(raw: str, kind: str, ident: str, *, available: bool,
             reason: str | None = None, **fields: Any) -> dict[str, Any]:
    return {
        "key": raw,
        "kind": kind,
        "id": ident,
        "available": available,
        "reason": reason,
        "name": None,
        "address": None,
        "verified": False,
        "data_source": "sayvors_analytics" if kind == "own" else "google_places",
        "tags": [],
        "location": {"latitude": None, "longitude": None, "distance_km": None, "category": None},
        "freshness": {"fetched_at": None, "age_seconds": None, "source": None, "stale": None},
        "metrics": _blank_metrics(),
        "facts": _blank_facts(),
        "notes": [],
        **fields,
    }


def _publish_time(value: Any) -> datetime | None:
    """Parse an RFC3339 timestamp from Google or a DB datetime."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _scan_reviews(reviews: list[dict]) -> dict[str, Any]:
    """Bounded rating/window/sentiment scan shared by both sides.

    Repeated text themes are extracted separately by ``theme_service``; this
    scan deliberately contains no domain keyword lists.
    """
    now = datetime.now(timezone.utc)
    windows = {key: 0 for key in WINDOW_DAYS}
    stars: Counter[int] = Counter()
    pos = neu = neg = 0

    for review in reviews:
        rating = review.get("rating")
        try:
            rating = int(rating) if rating is not None else None
        except (TypeError, ValueError):
            rating = None
        if rating in (1, 2, 3, 4, 5):
            stars[rating] += 1
            if rating >= 4:
                pos += 1
            elif rating == 3:
                neu += 1
            else:
                neg += 1

        published = _publish_time(review.get("publish_time") or review.get("created_at"))
        if published:
            for key, days in WINDOW_DAYS.items():
                if published >= now - timedelta(days=days):
                    windows[key] += 1

    total = pos + neu + neg
    return {
        "windows": windows,
        "stars": stars,
        "positive_pct": round(pos / total * 100, 1) if total else None,
        "negative_pct": round(neg / total * 100, 1) if total else None,
        "sample_size": len(reviews),
    }


def _place_types(types: list[str] | None) -> list[str]:
    """Map Google's place types to readable service labels, bounded to 10."""
    out = []
    for raw in (types or [])[:10]:
        name = str(raw)
        out.append(PLACE_TYPE_LABELS.get(name, name.replace("_", " ").title()))
    return list(dict.fromkeys(out))[:10]


def _nonnegative_int(value: Any) -> int | None:
    """Parse a provider count without letting malformed cache data break a column."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _sample_period_rating(reviews: list[dict], days: int) -> float | None:
    """Average rating of the sampled reviews published inside the window.

    Google only returns the most recent reviews, so this is a sample average,
    not the listing's official period rating. It is null rather than 0 when the
    sample holds nothing from the window.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    ratings: list[int] = []
    for review in reviews:
        try:
            rating = int(review.get("rating"))
        except (TypeError, ValueError):
            continue
        published = _publish_time(review.get("publish_time") or review.get("created_at"))
        if published and published >= cutoff and 1 <= rating <= 5:
            ratings.append(rating)
    return round(sum(ratings) / len(ratings), 2) if ratings else None


async def _baseline_snapshot(
    db: AsyncSession, tenant_id: str, place_pk: str, days: int
) -> BenchmarkSnapshot | None:
    """Newest snapshot taken at or before the start of the requested window."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    return (
        await db.execute(
            select(BenchmarkSnapshot)
            .where(
                BenchmarkSnapshot.tenant_id == tenant_id,
                BenchmarkSnapshot.place_id == place_pk,
                BenchmarkSnapshot.fetched_at <= cutoff,
            )
            .order_by(BenchmarkSnapshot.fetched_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


# Read handlers never call the free provider live: it is a paged scrape, not a
# page-load API. The worker / explicit refresh fills the cache.
CACHE_ONLY_SOURCES = {"boq", "gosom"}


def can_fetch_live(source: str) -> bool:
    """Whether a read handler can call the selected provider safely.

    On staging the default row may still say ``google_places`` without a key.
    Treating that as a live provider is what made saved-place details return
    503 and cards stick on "not ready". A source with no credentials serves the
    cache instead.
    """
    source = str(source or "").strip()
    if source in CACHE_ONLY_SOURCES:
        return False
    if source == "outscraper":
        return bool(outscraper.configured())
    if source == "google_places":
        return bool(places.configured())
    return False


async def _provider_details(
    source: str,
    place_id: str,
    *,
    reviews_limit: int,
    maps_url: str | None = None,
    cutoff: int | None = None,
    review_days: int | None = None,
) -> dict[str, Any]:
    """Provider-routed place details with an optional Places fallback.

    ``boq`` composes Google's public place-detail and review endpoints. Paid
    providers stay available when explicitly configured. A primary-provider
    failure falls back to Places only when a key exists; otherwise the original
    error is re-raised instead of making a doomed HTTP request.
    """
    source = str(source or "").strip()
    last_error: Exception | None = None
    if source in {"boq", "gosom"}:
        try:
            return await boq.get_place(
                place_id, reviews_limit=reviews_limit, maps_url=maps_url,
                days=review_days,
            )
        except boq.BoqError as exc:
            logger.warning("Free Google details failed for %s: %s", place_id, exc)
            last_error = exc
    elif source == "outscraper":
        try:
            return await outscraper.get_place(
                place_id, reviews_limit=10, cutoff=cutoff
            )
        except outscraper.OutscraperError as exc:
            logger.warning("outscraper details failed for %s: %s", place_id, exc)
            last_error = exc
    if not places.configured():
        if last_error is not None:
            raise last_error
        raise places.PlacesError("Google Places is not configured", 503)
    try:
        return await places.get_place(place_id, reviews_limit=10, cutoff=cutoff)
    except places.PlacesError:
        if last_error is not None:
            raise last_error
        raise


async def _saved_subject(db: AsyncSession, tenant_id: str, raw: str,
                         place_id: str, *,
                         days: int | None = None,
                         max_age_hours: int | None = None,
                         cache_enabled: bool = True,
                         source: str = "google_places") -> dict[str, Any]:
    saved = await service.get_saved(db, tenant_id, place_id)
    if saved is None:
        return _subject(raw, "saved", place_id, available=False,
                        reason="This business is not on your bench.")

    # A failed live refresh must not blank the column: the bench row already
    # holds the identity (label) and the numbers captured when it was saved.
    # Falling back to that is honest — returning a null column is not, because
    # the user did select a real business.
    now = datetime.now(timezone.utc)
    # SQLite drops the timezone on read; compare aware to avoid TypeError.
    cached_at = saved.fetched_at
    if cached_at and cached_at.tzinfo is None:
        cached_at = cached_at.replace(tzinfo=timezone.utc)

    # Period views serve from the cache when it is fresh; Live uses a live paid
    # provider when one exists. The free provider is always cache-only because
    # paging reviews inside a read handler would hold the DB session for seconds.
    use_cache = bool(
        not can_fetch_live(source) or (
            cache_enabled and days is not None and max_age_hours
            and cached_at and now - cached_at <= timedelta(hours=max_age_hours)
        )
    )
    live_failed = False
    if use_cache:
        details = {
            "name": saved.name,
            "address": saved.address,
            "types": saved.types,
            "rating": saved.rating,
            "review_count": saved.review_count,
            "reviews": saved.reviews,
        }
    else:
        cutoff_ts = int(now.timestamp()) - 7 * 24 * 3600
        try:
            details = await _provider_details(
                source, saved.place_id,
                reviews_limit=500, maps_url=saved.maps_url, cutoff=cutoff_ts,
            )
        except (places.PlacesError, boq.BoqError, outscraper.OutscraperError) as exc:
            logger.warning(
                "Comparison details failed for place %s: %s", saved.place_id, exc
            )
            details = {}
            live_failed = True
    if not use_cache and not live_failed and cache_enabled:
        # The live read doubles as the periodic scrape when none has run
        # yet, so history fills without waiting for the scraper.
        append = not await service.has_recent_snapshot(
            db, saved.id, hours=max_age_hours or 24, now=now
        )
        await service.store_place_details(
            db, saved, details, now=now, append_snapshot=append
        )

    name = str(details.get("name") or saved.name or saved.label or "").strip()
    reviews = list(details.get("reviews") or saved.reviews or [])[:REVIEW_SAMPLE_LIMIT]
    scan = _scan_reviews(reviews)
    total = details.get("review_count")
    if total is None:
        total = saved.review_count
    rating = details.get("rating")
    if rating is None:
        rating = saved.rating

    metrics = _blank_metrics()
    # An empty review sample means the windows are unknown, not zero: a zero
    # here would claim "no reviews in the last week", which Google never said.
    windows = scan["windows"] if scan["sample_size"] else {key: None for key in WINDOW_DAYS}
    scores = details.get("reviews_per_score") or saved.reviews_per_score or {}
    total_count = _nonnegative_int(total)
    five_count = _nonnegative_int(scores.get("5")) if isinstance(scores, dict) else None
    one_count = _nonnegative_int(scores.get("1")) if isinstance(scores, dict) else None
    full_distribution = (
        total_count is not None
        and total_count > 0
        and five_count is not None
        and one_count is not None
        and five_count <= total_count
        and one_count <= total_count
    )
    if full_distribution:
        five_star = five_count
        one_star = one_count
        star_share_base = total_count
    else:
        five_star = scan["stars"].get(5, 0) if scan["sample_size"] else None
        one_star = scan["stars"].get(1, 0) if scan["sample_size"] else None
        star_share_base = scan["sample_size"] or None
    metrics.update({
        "total_reviews": total,
        **windows,
        "avg_rating": rating,
        "total_ratings": total,
        "five_star": five_star,
        "four_star": scan["stars"].get(4, 0) if scan["sample_size"] else None,
        "one_star": one_star,
        "star_share_base": star_share_base,
    })
    facts = _blank_facts()
    facts.update({
        "positive_pct": scan["positive_pct"],
        "negative_pct": scan["negative_pct"],
        "branch": name or saved.label,
        "services": _place_types(details.get("types")),
    })

    notes: list[str] = []
    if live_failed:
        notes.append(
            "Google could not be reached just now, so this column shows the last known values."
        )
    if days is not None:
        baseline = await _baseline_snapshot(db, tenant_id, saved.id, days)
        metrics["period_avg_rating"] = _sample_period_rating(reviews, days)
        if baseline is None:
            metrics["period_reviews"] = None
            metrics["rating_change"] = None
            notes.insert(0, (
                "There is not enough data for this period yet, so reviews added "
                "and the rating change are blank."
            ))
        else:
            if total is not None and baseline.review_count is not None:
                metrics["period_reviews"] = max(0, int(total) - int(baseline.review_count))
            if rating is not None and baseline.rating is not None:
                metrics["rating_change"] = round(float(rating) - float(baseline.rating), 2)
            notes.insert(0, (
                "Reviews added and the rating change compare the latest values "
                "with the start of this period."
            ))
    if full_distribution:
        notes.append(
            "5-star and 1-star counts come from the provider's full rating distribution."
        )
    if scan["sample_size"]:
        evidence = "Review-window counts"
        if not full_distribution:
            evidence += " and star counts"
        notes.append(
            f"{evidence} come from the {scan['sample_size']} most recent reviews "
            f"Google returns (max {REVIEW_SAMPLE_LIMIT}), not the lifetime total."
        )
    elif not full_distribution:
        notes.append(
            "No reviews were available in this refresh, so review-window and "
            "star facts are blank."
        )
    notes.append("Views, calls, menu prices and registered staff are only available to the listing owner.")

    fetched_iso = cached_at.isoformat() if cached_at else None
    age_seconds = int((now - cached_at).total_seconds()) if cached_at else None
    stale = bool(max_age_hours and cached_at and (now - cached_at) > timedelta(hours=max_age_hours))
    types = details.get("types") or saved.types or []
    category = _place_types(types)[0] if _place_types(types) else None
    lat = saved.latitude if saved.latitude is not None else details.get("latitude")
    lng = saved.longitude if saved.longitude is not None else details.get("longitude")
    try:
        lat = float(lat) if lat is not None else None
        lng = float(lng) if lng is not None else None
    except Exception:
        lat = lng = None
    return _subject(
        raw, "saved", place_id, available=True,
        name=name or "Saved business",
        address=details.get("address"),
        location={"latitude": lat, "longitude": lng, "distance_km": None, "category": category},
        freshness={
            "fetched_at": fetched_iso,
            "age_seconds": age_seconds,
            "source": source,
            "stale": stale if cached_at else None,
        },
        metrics=metrics, facts=facts,
        notes=notes,
    )


async def _own_subject(db: AsyncSession, tenant_id: str, raw: str,
                       channel_id: str, *,
                       days: int | None = None) -> dict[str, Any]:
    channel = (
        await db.execute(
            select(Channel).where(Channel.id == channel_id, Channel.user_id == tenant_id)
        )
    ).scalar_one_or_none()
    if channel is None:
        return _subject(raw, "own", channel_id, available=False,
                        reason="This location is not connected to your workspace.")
    if channel.platform != "google_reviews":
        return _subject(raw, "own", channel_id, available=False,
                        reason="Only Google Business Profile locations can be compared.")

    overview = await get_overview(db, tenant_id, channel_id, days=365)
    bucket = func.coalesce(ReviewInsight.review_updated_at, ReviewInsight.created_at)
    now = datetime.now(timezone.utc)
    base = [
        ReviewInsight.user_id == tenant_id,
        ReviewInsight.channel_id == channel_id,
        ReviewInsight.removed_at.is_(None),
    ]
    window_row = (
        await db.execute(
            select(*[
                func.sum(case((bucket >= now - timedelta(days=days), 1), else_=0))
                for days in WINDOW_DAYS.values()
            ]).where(*base)
        )
    ).one()
    windows = {
        key: int(window_row[i] or 0) for i, key in enumerate(WINDOW_DAYS)
    }

    sample_rows = (
        await db.execute(
            select(
                ReviewInsight.review_text, ReviewInsight.rating,
                ReviewInsight.topics, ReviewInsight.problems,
            )
            .where(*base)
            .order_by(bucket.desc())
            .limit(REVIEW_SAMPLE_LIMIT)
        )
    ).all()
    sample = [
        {"text": row[0], "rating": row[1]} for row in sample_rows
    ]
    scan = _scan_reviews(sample)

    problems: Counter[str] = Counter()
    for row in sample_rows:
        for problem in (row[3] or []) if isinstance(row[3], list) else []:
            if isinstance(problem, dict) and problem.get("name"):
                problems[str(problem["name"])[:120]] += 1

    service_rows = (
        await db.execute(
            select(BusinessService.name)
            .where(BusinessService.channel_id == channel_id, BusinessService.is_offered.is_(True))
            .order_by(BusinessService.name)
            .limit(20)
        )
    ).scalars().all()
    services = [str(name)[:120] for name in service_rows]

    listing_id = await listing_id_for_channel(db, channel_id)
    named = await staff_summary(db, user_id=tenant_id, listing_id=listing_id, days=365)
    named_team = [
        {"name": item["name"], "mentions": item["mentions"], "positive": item["positive"]}
        for item in named if item.get("mentions")
    ][:5]

    verification = (
        await db.execute(
            select(VerificationRecord).where(VerificationRecord.channel_id == channel_id)
        )
    ).scalar_one_or_none()
    verified = bool(
        verification
        and (verification.status == "verified" or verification.verified_at is not None)
    )

    distribution = overview.get("rating_distribution") or {}
    google_perf = overview.get("google_performance") or {}
    sentiment = overview.get("sentiment") or {}
    distribution = {str(k): int(v or 0) for k, v in distribution.items()}

    metrics = _blank_metrics()
    metrics.update({
        "total_reviews": overview.get("total_reviews"),
        **windows,
        "avg_rating": overview.get("avg_rating"),
        "total_ratings": overview.get("total_reviews"),
        "five_star": distribution.get("5"),
        "four_star": distribution.get("4"),
        "one_star": distribution.get("1"),
        "star_share_base": overview.get("total_reviews"),
        "impressions": google_perf.get("impressions_maps"),
        "calls": google_perf.get("call_clicks"),
    })
    facts = _blank_facts()
    facts.update({
        "positive_pct": sentiment.get("positive_pct"),
        "negative_pct": sentiment.get("negative_pct"),
        "branch": channel.display_name,
        "services": services,
        "top_problems": [name for name, _ in problems.most_common(5)],
        "named_team": named_team,
    })

    notes = [
        f"Counts come from your connected Google location. Top problems are counted "
        f"from the {scan['sample_size']} most recent stored reviews "
        f"(max {REVIEW_SAMPLE_LIMIT}).",
        "Views and calls are from the last 12 months of Google Business Profile data.",
    ]
    if days is not None:
        cutoff = now - timedelta(days=days)
        # Review facts come from the review rows themselves: a review published
        # inside the window is a fact, not an estimate. The rating change is the
        # lifetime average now against the lifetime average on the day the
        # window opened — the same definition used for a saved competitor.
        prev_cutoff = cutoff - timedelta(days=days)
        period_row = (
            await db.execute(
                select(
                    func.sum(case((bucket >= cutoff, 1), else_=0)),
                    func.avg(case((bucket >= cutoff, ReviewInsight.rating))),
                    func.avg(case((bucket < cutoff, ReviewInsight.rating))),
                    func.sum(case(((bucket >= prev_cutoff) & (bucket < cutoff), 1), else_=0)),
                    func.avg(case(((bucket >= prev_cutoff) & (bucket < cutoff), ReviewInsight.rating))),
                ).where(*base)
            )
        ).one()
        period_reviews = int(period_row[0] or 0)
        period_avg = (
            round(float(period_row[1]), 2) if period_row[1] is not None else None
        )
        before_avg = (
            round(float(period_row[2]), 2) if period_row[2] is not None else None
        )
        prev_period_reviews = int(period_row[3] or 0)
        prev_period_avg = (
            round(float(period_row[4]), 2) if period_row[4] is not None else None
        )
        current_avg = overview.get("avg_rating")
        rating_change = None
        if (
            int(overview.get("total_reviews") or 0) > 0
            and current_avg is not None
            and before_avg is not None
        ):
            rating_change = round(float(current_avg) - before_avg, 2)
        period_reviews_delta = period_reviews - prev_period_reviews
        period_avg_rating_delta = (
            round(period_avg - prev_period_avg, 2)
            if period_avg is not None and prev_period_avg is not None
            else None
        )

        # No rows means Google has not synced performance for this window yet.
        # A zero would claim the location was never seen, which we do not know.
        perf_row = (
            await db.execute(
                select(
                    func.count(),
                    func.sum(LocationDailyMetric.impressions_maps_desktop),
                    func.sum(LocationDailyMetric.impressions_maps_mobile),
                    func.sum(LocationDailyMetric.call_clicks),
                ).where(
                    LocationDailyMetric.user_id == tenant_id,
                    LocationDailyMetric.channel_id == channel_id,
                    LocationDailyMetric.date >= cutoff.date(),
                )
            )
        ).one()
        has_perf = int(perf_row[0] or 0) > 0
        metrics.update({
            "period_reviews": period_reviews,
            "period_avg_rating": period_avg,
            "rating_change": rating_change,
            "period_impressions": (
                int(perf_row[1] or 0) + int(perf_row[2] or 0) if has_perf else None
            ),
            "period_calls": int(perf_row[3] or 0) if has_perf else None,
            "prev_period_reviews": prev_period_reviews,
            "prev_period_avg_rating": prev_period_avg,
            "period_reviews_delta": period_reviews_delta,
            "period_avg_rating_delta": period_avg_rating_delta,
        })
        notes.insert(
            0,
            f"Reviews added, average rating, views and calls cover the last "
            f"{days} days of your connected location.",
        )

    meta: dict[str, Any] = {}
    try:
        meta = json.loads(channel.metadata_json or "{}")
    except Exception:
        meta = {}
    if not isinstance(meta, dict):
        meta = {}
    lat = meta.get("latitude") or meta.get("lat")
    lng = meta.get("longitude") or meta.get("lng")
    try:
        lat = float(lat) if lat is not None else None
        lng = float(lng) if lng is not None else None
    except Exception:
        lat = lng = None
    address = str(meta.get("address") or meta.get("formatted_address") or "").strip() or None
    category = (
        str(meta.get("primary_category") or meta.get("category") or "").strip() or None
    )
    return _subject(
        raw, "own", channel_id, available=True,
        name=channel.display_name,
        address=address,
        verified=verified,
        tags=_channel_tags(channel),
        location={"latitude": lat, "longitude": lng, "distance_km": None, "category": category},
        freshness={"fetched_at": None, "age_seconds": None, "source": "sayvors_analytics", "stale": None},
        metrics=metrics, facts=facts,
        notes=notes,
    )


async def compare_subjects(db: AsyncSession, tenant_id: str,
                           raw_subjects: list[str], *,
                           days: int | None = None) -> list[dict[str, Any]]:
    """Return one normalized record per requested subject, in request order.

    `days` switches the period facts from null to a window: saved places get
    them from snapshot history, own locations from their review and performance
    rows. `None` means "live" — only the current values.

    A bad or inaccessible side is returned as an unavailable record instead of
    failing the whole comparison, so the other side still renders.
    """
    if not raw_subjects or len(raw_subjects) > MAX_SUBJECTS:
        raise CompareError(f"Compare between one and {MAX_SUBJECTS} subjects.")
    config = await service.get_config(db)
    out = []
    for raw in raw_subjects:
        try:
            kind, ident = parse_subject(raw)
            if kind == "saved":
                out.append(await _saved_subject(
                    db, tenant_id, raw, ident,
                    days=days,
                    max_age_hours=config.refresh_hours,
                    cache_enabled=config.place_cache_enabled,
                    source=config.source,
                ))
            else:
                out.append(await _own_subject(db, tenant_id, raw, ident, days=days))
        except CompareError as exc:
            out.append(_subject(str(raw), "unknown", "", available=False, reason=str(exc)))
        except Exception:
            # One side failing must never take the other down; log with context.
            logger.exception("Comparison subject failed: %s", raw)
            out.append(_subject(
                str(raw), "unknown", "", available=False,
                reason="Could not load this side of the comparison.",
            ))
    anchor = next(
        (s for s in out if s.get("kind") == "own" and s.get("available")
         and isinstance((s.get("location") or {}).get("latitude"), (int, float))
         and isinstance((s.get("location") or {}).get("longitude"), (int, float))),
        None,
    )
    if anchor:
        a_lat = float(anchor["location"]["latitude"])
        a_lng = float(anchor["location"]["longitude"])
        for s in out:
            loc = s.get("location") or {}
            lat = loc.get("latitude")
            lng = loc.get("longitude")
            if isinstance(lat, (int, float)) and isinstance(lng, (int, float)):
                s["location"]["distance_km"] = round(_haversine_km(a_lat, a_lng, float(lat), float(lng)), 2)
            else:
                s["location"]["distance_km"] = None
    return out


MAX_HISTORY_POINTS = 24


async def _saved_history(
    db: AsyncSession, tenant_id: str, raw: str, place_id: str,
    *, days: int, points: int,
) -> dict[str, Any]:
    """Snapshot history of one bench place. Empty until the scraper has run."""
    saved = await service.get_saved(db, tenant_id, place_id)
    if saved is None:
        return {"key": raw, "kind": "saved", "name": None, "points": []}
    rows = await service.history_points(db, tenant_id, saved, days=days, points=points)
    return {
        "key": raw,
        "kind": "saved",
        "name": saved.name or saved.label,
        "points": rows,
    }


async def _own_history(
    db: AsyncSession, tenant_id: str, raw: str, channel_id: str,
    *, days: int, points: int,
) -> dict[str, Any]:
    """Cumulative review totals for one own location, sampled across the window.

    One aggregate query covers every checkpoint, so a year of history costs the
    same as a month. Checkpoints with no reviews are dropped rather than shown
    as zeroes.
    """
    channel = (
        await db.execute(
            select(Channel).where(Channel.id == channel_id, Channel.user_id == tenant_id)
        )
    ).scalar_one_or_none()
    if channel is None or channel.platform != "google_reviews":
        return {"key": raw, "kind": "own", "name": None, "points": []}

    count = max(2, points)
    now = datetime.now(timezone.utc)
    step = timedelta(days=max(1, days)) / count
    checkpoints = [now - step * (count - index - 1) for index in range(count)]
    bucket = func.coalesce(ReviewInsight.review_updated_at, ReviewInsight.created_at)
    result = (
        await db.execute(
            select(
                *[
                    func.sum(case((bucket <= when, 1), else_=0))
                    for when in checkpoints
                ],
                *[
                    func.avg(case((bucket <= when, ReviewInsight.rating)))
                    for when in checkpoints
                ],
            ).where(
                ReviewInsight.user_id == tenant_id,
                ReviewInsight.channel_id == channel_id,
                ReviewInsight.removed_at.is_(None),
            )
        )
    ).one()

    rows = []
    for index, when in enumerate(checkpoints):
        total = int(result[index] or 0)
        if total == 0:
            continue
        average = result[count + index]
        rows.append({
            "at": when.isoformat(),
            "rating": round(float(average), 2) if average is not None else None,
            "reviews": total,
        })
    return {
        "key": raw,
        "kind": "own",
        "name": channel.display_name,
        "points": rows,
    }


async def subject_history(
    db: AsyncSession, tenant_id: str, raw_subjects: list[str],
    *, days: int, points: int,
) -> dict[str, Any]:
    """Bounded history for each requested subject, oldest point first."""
    if not raw_subjects or len(raw_subjects) > MAX_SUBJECTS:
        raise CompareError(f"Ask for history of one to {MAX_SUBJECTS} subjects.")
    points = max(2, min(int(points), MAX_HISTORY_POINTS))
    days = max(1, int(days))
    out = []
    for raw in raw_subjects:
        try:
            kind, ident = parse_subject(raw)
            if kind == "saved":
                out.append(await _saved_history(
                    db, tenant_id, raw, ident, days=days, points=points
                ))
            else:
                out.append(await _own_history(
                    db, tenant_id, raw, ident, days=days, points=points
                ))
        except CompareError:
            out.append({"key": str(raw), "kind": "unknown", "name": None, "points": []})
        except Exception:
            logger.exception("History failed for subject: %s", raw)
            out.append({"key": str(raw), "kind": "unknown", "name": None, "points": []})
    return {"days": days, "points": points, "subjects": out}


# ── Reviews table ─────────────────────────────────────────────────────────


def _sentiment_label(rating: Any) -> str:
    """Sentiment of a single review for the reviews table.

    Same rule the scan uses for its counts: a rating of 4+ is positive, 3 is
    neutral, and anything else is negative. Google's own text sentiment is
    used for our own locations (see `_own_reviews`).
    """
    try:
        value = int(rating)
    except (TypeError, ValueError):
        return "neutral"
    if value >= 4:
        return "positive"
    if value == 3:
        return "neutral"
    return "negative"


async def _saved_reviews(
    db: AsyncSession, tenant_id: str, place_id: str, *, limit: int,
    source: str = "google_places",
) -> tuple[str | None, list[dict[str, Any]], dict[str, Any]]:
    """Newest cached review sample for a saved place.

    The cached sample wins so the reviews table costs nothing per page load;
    a live provider call fills it when empty (bounded, and honest).
    """
    saved = await service.get_saved(db, tenant_id, place_id)
    if saved is None:
        return None, [], {
            "total": None, "sampled": 0, "answered": 0,
            "unanswered": 0, "response_rate": None,
            "evidence_basis": "unavailable",
        }
    name = saved.name or saved.label
    reviews = list(saved.reviews or [])
    # The free provider never scrapes inside a read handler. The worker /
    # explicit refresh fills the cache; paid providers may fill an empty sample.
    if not reviews and can_fetch_live(source):
        cutoff_ts = int(datetime.now(timezone.utc).timestamp()) - 7 * 24 * 3600
        try:
            details = await _provider_details(
                source, saved.place_id,
                reviews_limit=50, maps_url=saved.maps_url, cutoff=cutoff_ts,
            )
        except (places.PlacesError, boq.BoqError, outscraper.OutscraperError):
            details = {}
        reviews = list(details.get("reviews") or [])
    sample = reviews[:limit]
    out = []
    for review in sample:
        rating = review.get("rating")
        published = _publish_time(review.get("publish_time") or review.get("created_at"))
        answer = str(review.get("owner_answer") or "").strip()
        answer_time = _publish_time(review.get("owner_answer_time"))
        out.append({
            "rating": rating,
            "time": published.isoformat() if published else None,
            "sentiment": _sentiment_label(rating),
            "text": str(review.get("text") or "")[:REVIEW_TEXT_MAX],
            "author": review.get("author"),
            "author_photo": review.get("author_photo"),
            "answered": bool(answer),
            "owner_answer": answer[:REVIEW_TEXT_MAX] or None,
            "owner_answer_time": answer_time.isoformat() if answer_time else None,
            # Places-sourced reviews carry no complaint themes.
            "problems": [],
        })
    answered = sum(1 for review in out if review["answered"])
    sampled = len(out)
    summary = {
        "total": saved.review_count if saved.review_count is not None else len(reviews),
        "sampled": sampled,
        "answered": answered,
        "unanswered": sampled - answered,
        "response_rate": round(answered / sampled * 100, 1) if sampled else None,
        "evidence_basis": "cached_sample",
    }
    return name, out, summary


async def _own_reviews(
    db: AsyncSession, tenant_id: str, channel_id: str, *, limit: int
) -> tuple[str | None, list[dict[str, Any]], dict[str, Any]]:
    """Newest stored reviews of one of the tenant's own locations, from analytics."""
    channel = (
        await db.execute(
            select(Channel).where(Channel.id == channel_id, Channel.user_id == tenant_id)
        )
    ).scalar_one_or_none()
    if channel is None:
        return None, [], {
            "total": None, "sampled": 0, "answered": 0,
            "unanswered": 0, "response_rate": None,
            "evidence_basis": "unavailable",
        }
    bucket = func.coalesce(ReviewInsight.review_updated_at, ReviewInsight.created_at)
    rows = (
        await db.execute(
            select(
                ReviewInsight.rating,
                ReviewInsight.review_text,
                ReviewInsight.sentiment,
                ReviewInsight.problems,
                ReviewInsight.reviewer_name,
                ReviewInsight.reviewer_photo_url,
                ReviewInsight.replied,
                bucket,
            ).where(
                ReviewInsight.user_id == tenant_id,
                ReviewInsight.channel_id == channel_id,
                ReviewInsight.removed_at.is_(None),
            ).order_by(bucket.desc()).limit(limit)
        )
    ).all()
    out = []
    for rating, text, sentiment, problems, reviewer, photo, replied, published in rows:
        stored = (
            sentiment if sentiment in ("positive", "neutral", "negative")
            else None
        )
        out.append({
            "rating": rating,
            "time": published.isoformat() if published else None,
            # Prefer the team-classified sentiment for our own locations.
            "sentiment": stored or _sentiment_label(rating),
            "text": str(text or "")[:REVIEW_TEXT_MAX],
            "author": str(reviewer)[:255] if reviewer else None,
            "author_photo": str(photo)[:1024] if photo else None,
            "answered": bool(replied),
            "owner_answer": None,
            "owner_answer_time": None,
            "problems": [str(item)[:120] for item in (problems or [])][:10],
        })
    totals = (
        await db.execute(
            select(
                func.count(),
                func.sum(case((ReviewInsight.replied.is_(True), 1), else_=0)),
            ).where(
                ReviewInsight.user_id == tenant_id,
                ReviewInsight.channel_id == channel_id,
                ReviewInsight.removed_at.is_(None),
            )
        )
    ).one()
    total = int(totals[0] or 0)
    answered = int(totals[1] or 0)
    summary = {
        "total": total,
        "sampled": len(out),
        "answered": answered,
        "unanswered": total - answered,
        "response_rate": round(answered / total * 100, 1) if total else None,
        "evidence_basis": "stored_lifetime",
    }
    return channel.display_name, out, summary


async def reviews_for(
    db: AsyncSession,
    tenant_id: str,
    raw_subjects: list[str],
    *,
    limit: int = MAX_REVIEWS_PER_SUBJECT,
) -> dict[str, Any]:
    """Newest review samples per subject, for the paginated reviews table.

    A bad or inaccessible subject is returned with an empty review list instead
    of failing the whole table, mirroring `compare_subjects`.
    """
    if not raw_subjects or len(raw_subjects) > MAX_SUBJECTS:
        raise CompareError(f"Ask for reviews of one to {MAX_SUBJECTS} subjects.")
    limit = max(1, min(int(limit), MAX_REVIEWS_PER_SUBJECT))
    config = await service.get_config(db)
    out = []
    for raw in raw_subjects:
        summary = {
            "total": None, "sampled": 0, "answered": 0,
            "unanswered": 0, "response_rate": None,
            "evidence_basis": "unavailable",
        }
        try:
            kind, ident = parse_subject(raw)
            if kind == "saved":
                name, reviews, summary = await _saved_reviews(
                    db, tenant_id, ident, limit=limit, source=config.source
                )
            else:
                name, reviews, summary = await _own_reviews(db, tenant_id, ident, limit=limit)
        except CompareError:
            name, reviews = None, []
        except Exception:
            logger.exception("Reviews failed for subject: %s", raw)
            name, reviews = None, []
        out.append({"key": str(raw), "name": name, "reviews": reviews, "summary": summary})
    return {"subjects": out}

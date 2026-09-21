"""Google Business Profile performance sync worker.

Periodically pulls daily performance metrics (impressions, website clicks,
calls, direction requests) for every active Google Reviews channel via the
Business Profile Performance API and upserts them into
`location_daily_metrics`. Each sync also emits a `metrics.synced` event to
Kafka through the outbox so downstream systems can react to fresh data.

Kafka/Google outages degrade gracefully: the loop logs and retries.

Mock policy: GOOGLE_REVIEWS_MOCK mode NEVER persists anything. Fabricated
metrics used to be written into this table and surfaced as real dashboard
numbers — that path is removed. In mock mode the sync is a logged no-op.
"""
import asyncio
import importlib
import json
import logging
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select

from ...config import settings
from ...database import async_session
from ..channels.google_reviews import GoogleReviewsClient, GoogleReviewsError
from ..channels.models import Channel
from ..channels.service import decrypt_token
from ..outbox.service import enqueue_event
from .models import LocationDailyMetric, SearchKeywordStat

logger = logging.getLogger(__name__)

# integrations/ lives at the repo root (same pattern as localith/service.py).
_API_ROOT = Path(__file__).resolve().parents[4]
_REPO_ROOT = _API_ROOT.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
embedsocial = importlib.import_module("integrations.channels.embedsocial")  # type: ignore[arg-type]

# Metric name -> LocationDailyMetric column
_METRIC_COLUMNS = {
    "WEBSITE_CLICKS": "website_clicks",
    "CALL_CLICKS": "call_clicks",
    "DIRECTION_REQUESTS": "direction_requests",
    "BUSINESS_IMPRESSIONS_DESKTOP": "impressions_maps_desktop",
    "BUSINESS_IMPRESSIONS_MOBILE": "impressions_maps_mobile",
}


def _channel_meta(channel: Channel) -> dict:
    try:
        return json.loads(channel.metadata_json or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}


async def _sync_channel(channel: Channel) -> int:
    """Sync one channel; returns the number of days upserted."""
    if settings.GOOGLE_REVIEWS_MOCK:
        logger.info(
            "Performance sync: mock mode — skipping persistence for channel %s",
            channel.id,
        )
        return 0
    location_id = _channel_meta(channel).get("location_id", "")
    if not location_id:
        logger.warning("Performance sync: channel %s has no location_id", channel.id)
        return 0

    end_date = datetime.now(timezone.utc).date() - timedelta(days=1)  # Google lags ~1 day
    start_date = end_date - timedelta(days=settings.ANALYTICS_PERFORMANCE_DAYS_BACK)

    access_token = decrypt_token(channel.access_token) if channel.access_token else None
    refresh_token = decrypt_token(channel.refresh_token) if channel.refresh_token else None
    if not access_token and not refresh_token:
        # No OAuth tokens: Localith-backed channel. Same table, same shape —
        # pulled from Localith's daily metrics instead of Google's.
        return await _sync_localith_channel(channel)
    client = GoogleReviewsClient(access_token or "", refresh_token)
    client.set_known_expiry(channel.token_expires_at)
    try:
        series = await client.fetch_performance_timeseries(location_id, start_date, end_date)
        try:
            keywords = await client.fetch_keyword_timeseries(location_id, start_date, end_date)
        except GoogleReviewsError as e:
            logger.warning("Keyword metrics unavailable for %s: %s", channel.id, e)
            keywords = {}
    finally:
        await client.close()

    days_touched: set = set()
    async with async_session() as db:
        for metric, dated_values in series.items():
            column = _METRIC_COLUMNS.get(metric)
            if not column:
                continue
            for day, value in dated_values:
                row = (
                    await db.execute(
                        select(LocationDailyMetric).where(
                            LocationDailyMetric.channel_id == channel.id,
                            LocationDailyMetric.date == day,
                        )
                    )
                ).scalar_one_or_none()
                if not row:
                    row = LocationDailyMetric(
                        id=str(uuid.uuid4()),
                        channel_id=channel.id,
                        user_id=channel.user_id,
                        date=day,
                    )
                setattr(row, column, int(value))
                db.add(row)
                days_touched.add(day)
        for keyword, dated_values in keywords.items():
            for day, value in dated_values:
                existing = (
                    await db.execute(
                        select(SearchKeywordStat).where(
                            SearchKeywordStat.channel_id == channel.id,
                            SearchKeywordStat.keyword == keyword,
                            SearchKeywordStat.date == day,
                        )
                    )
                ).scalar_one_or_none()
                if existing:
                    existing.impressions = int(value)
                    db.add(existing)
                else:
                    db.add(SearchKeywordStat(
                        id=str(uuid.uuid4()),
                        user_id=channel.user_id,
                        channel_id=channel.id,
                        keyword=keyword,
                        date=day,
                        impressions=int(value),
                    ))
        await db.commit()

    # Emit one Kafka event per synced day (summary payload)
    for day in sorted(days_touched):
        await enqueue_event(
            "metrics.synced",
            {
                "user_id": channel.user_id,
                "channel_id": channel.id,
                "date": day.isoformat(),
                "metrics": {
                    _METRIC_COLUMNS[m]: dict(series.get(m, {})).get(day, 0)
                    for m in _METRIC_COLUMNS
                    if m in series
                },
            },
            topic="metrics-events",
        )
    return len(days_touched)


# Localith daily ingest: same table as the OAuth path, so charts can't tell
# the source apart. Backfill is self-completing — each pass syncs up to
# _LOCALITH_DAYS_PER_PASS missing days (oldest first); afterwards only the
# trailing window refreshes.
_LOCALITH_BACKFILL_DAYS = 90
_LOCALITH_DAYS_PER_PASS = 14


async def _upsert_localith_day(db, channel: Channel, day, nums: dict) -> None:
    """Write one Localith day into the same table the OAuth path uses."""
    row = (
        await db.execute(
            select(LocationDailyMetric).where(
                LocationDailyMetric.channel_id == channel.id,
                LocationDailyMetric.date == day,
            )
        )
    ).scalar_one_or_none()
    if not row:
        row = LocationDailyMetric(
            id=str(uuid.uuid4()),
            channel_id=channel.id,
            user_id=channel.user_id,
            date=day,
        )
    row.impressions_maps_desktop = nums["impressions_maps_desktop"]
    row.impressions_maps_mobile = nums["impressions_maps_mobile"]
    row.website_clicks = nums["website_clicks"]
    row.call_clicks = nums["call_clicks"]
    row.direction_requests = nums["direction_requests"]
    row.extra = {
        "impressions_search": nums["impressions_search"],
        "messages": nums["messages"],
        "bookings": nums["bookings"],
        "source": "localith",
    }
    db.add(row)


async def _sync_localith_channel(channel: Channel) -> int:
    """Daily metrics for a Localith-backed channel via single-day calls."""
    meta = _channel_meta(channel)
    listing_id = meta.get("listing_id") or meta.get("location_id") or ""
    if not listing_id:
        logger.warning("Performance sync: channel %s has no listing id", channel.id)
        return 0

    end_date = datetime.now(timezone.utc).date() - timedelta(days=1)
    async with async_session() as db:
        latest = (
            await db.execute(
                select(LocationDailyMetric.date)
                .where(LocationDailyMetric.channel_id == channel.id)
                .order_by(LocationDailyMetric.date.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        oldest_wanted = end_date - timedelta(days=_LOCALITH_BACKFILL_DAYS - 1)
        start_date = max(
            (latest + timedelta(days=1)) if latest else oldest_wanted,
            oldest_wanted,
        )
        # Cap the per-pass workload; the next pass continues where we stop.
        days = [
            start_date + timedelta(days=i)
            for i in range(min((end_date - start_date).days + 1, _LOCALITH_DAYS_PER_PASS))
            if start_date + timedelta(days=i) <= end_date
        ]
        if not days:
            return 0
        touched_days: set = set()
        for day in days:
            try:
                nums = await asyncio.to_thread(
                    embedsocial.fetch_listing_metrics_for_day, listing_id, day
                )
            except Exception as e:
                logger.warning(
                    "Localith daily metrics failed for %s on %s: %s",
                    channel.id, day.isoformat(), e,
                )
                continue
            await _upsert_localith_day(db, channel, day, nums)
            touched_days.add(day)
        await db.commit()

    for day in sorted(touched_days):
        await enqueue_event(
            "metrics.synced",
            {"user_id": channel.user_id, "channel_id": channel.id,
             "date": day.isoformat(), "source": "localith"},
            topic="metrics-events",
        )
    return len(touched_days)


async def run_performance_sync_worker() -> None:
    """Background loop started from app lifespan."""
    interval = max(300, settings.ANALYTICS_PERFORMANCE_SYNC_INTERVAL_SECONDS)
    while True:
        try:
            await sync_all()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("Performance sync pass failed: %s", e)
        await asyncio.sleep(interval)


async def sync_all() -> dict:
    """One sync pass over all active Google Reviews channels. Returns totals."""
    totals = {"channels": 0, "days": 0, "errors": 0}
    async with async_session() as db:
        channels = (
            await db.execute(
                select(Channel).where(
                    Channel.platform == "google_reviews",
                    Channel.status == "active",
                )
            )
        ).scalars().all()

        for channel in channels:
            totals["channels"] += 1
            try:
                totals["days"] += await _sync_channel(channel)
            except GoogleReviewsError as e:
                logger.warning("Performance sync failed for %s: %s", channel.id, e)
                totals["errors"] += 1
            except Exception as e:
                logger.exception("Performance sync error for %s: %s", channel.id, e)
                totals["errors"] += 1
    if totals["channels"]:
        logger.info("Performance sync: %s", totals)
    return totals

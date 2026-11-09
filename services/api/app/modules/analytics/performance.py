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
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from ...config import settings
from ...database import async_session
from ..channels.google_reviews import GoogleReviewsClient, GoogleReviewsError
from ..channels.models import Channel
from ..channels.service import decrypt_token
from ..outbox.service import enqueue_event
from ..notifications.service import notify
from .models import LocationDailyMetric, SearchKeywordStat

logger = logging.getLogger(__name__)

# Metric name -> LocationDailyMetric column. These are the current
# Business Profile Performance API enum names; the old DIRECTION_REQUESTS /
# BUSINESS_IMPRESSIONS_DESKTOP / _MOBILE names are rejected by Google.
_METRIC_COLUMNS = {
    "WEBSITE_CLICKS": "website_clicks",
    "CALL_CLICKS": "call_clicks",
    "BUSINESS_DIRECTION_REQUESTS": "direction_requests",
    "BUSINESS_IMPRESSIONS_DESKTOP_MAPS": "impressions_maps_desktop",
    "BUSINESS_IMPRESSIONS_MOBILE_MAPS": "impressions_maps_mobile",
}
# Search impressions have no dedicated column; they ride in `extra` and are
# summed from desktop + mobile into one per-day value.
_SEARCH_IMPRESSION_METRICS = (
    "BUSINESS_IMPRESSIONS_DESKTOP_SEARCH",
    "BUSINESS_IMPRESSIONS_MOBILE_SEARCH",
)


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
        # A channel without OAuth tokens cannot reach Google; skip it instead
        # of burning a request. Historical rows remain readable.
        logger.debug(
            "Performance sync skipped for %s: no Google OAuth credentials",
            channel.id,
        )
        return 0
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

    # Search impressions are split desktop/mobile by Google but share one
    # `extra.impressions_search` value in the daily row.
    search_totals: dict = {}
    for metric in _SEARCH_IMPRESSION_METRICS:
        for day, value in series.get(metric, []):
            search_totals[day] = search_totals.get(day, 0) + int(value)

    days_touched: set = set()
    # Days with no prior row = genuinely new data. Steady-state re-syncs of
    # already-known days stay silent; only a new day rings the bell, so the
    # feed shows at most one metrics notification per channel per day.
    new_days: set = set()
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
                    new_days.add(day)
                setattr(row, column, int(value))
                if day in search_totals:
                    extra = dict(row.extra) if isinstance(row.extra, dict) else {}
                    extra["impressions_search"] = search_totals[day]
                    row.extra = extra
                db.add(row)
                days_touched.add(day)
        # A day can have search impressions but no maps/action metric; it
        # still needs a row so the growth charts see the search views.
        for day, value in search_totals.items():
            if day in days_touched:
                continue
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
                new_days.add(day)
            extra = dict(row.extra) if isinstance(row.extra, dict) else {}
            extra["impressions_search"] = value
            row.extra = extra
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
        # Emit one Kafka event per synced day (summary payload), atomically
        # with the metric upserts so a crash cannot lose the notification.
        from ..outbox.service import enqueue_event_in

        for day in sorted(days_touched):
            await enqueue_event_in(
                db,
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
        # One bell per pass that imported genuinely-new days — the summary
        # shows the latest day's numbers so the merchant can see the sync
        # actually brought data. A first-ever connect collapses ~30 days
        # into this single notification instead of one per day.
        if new_days:
            latest = max(new_days)

            def _val(metric: str) -> int:
                for day, value in series.get(metric, []):
                    if day == latest:
                        return int(value)
                return 0

            impressions = (
                _val("BUSINESS_IMPRESSIONS_DESKTOP_MAPS")
                + _val("BUSINESS_IMPRESSIONS_MOBILE_MAPS")
                + int(search_totals.get(latest, 0))
            )
            await notify(
                db,
                channel.user_id,
                "metrics_synced",
                f"{len(new_days)} new day{'s' if len(new_days) != 1 else ''} of Google profile metrics synced",
                (
                    f"Impressions {impressions} · Calls {_val('CALL_CLICKS')}"
                    f" · Website clicks {_val('WEBSITE_CLICKS')}"
                    f" · Directions {_val('BUSINESS_DIRECTION_REQUESTS')}"
                    f" — latest day {latest.isoformat()}"
                ),
                data={"days": len(new_days), "listing": channel.display_name or ""},
                href="/dashboard/growth",
            )
        await db.commit()
    return len(days_touched)


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

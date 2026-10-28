"""Market benchmarks aggregation worker.

Cross-tenant aggregation: reads all tenants' stored `channel_daily_metrics`
rows, computes median/p25/p75 for key metrics, and upserts into the
`market_benchmarks` table. Runs daily. Endpoints read stored rows only —
no cross-tenant queries on the request path (architecture rule).

Aggregates only — no per-tenant data is stored or exposed.
"""
import asyncio
import logging
import statistics
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, func

from ...config import settings
from ...database import async_session
from ..analytics.models import ChannelDailyMetric, MarketBenchmark

logger = logging.getLogger(__name__)

_WINDOW_DAYS = 30


def _percentile(sorted_vals: list[float], q: float) -> float | None:
    if not sorted_vals:
        return None
    n = len(sorted_vals)
    k = min(n - 1, max(0, int(q * (n - 1))))
    return round(sorted_vals[k], 2)


async def aggregate_once(session_factory=None) -> dict:
    """One pass: aggregate all tenants' dailies into market_benchmarks."""
    from ...database import async_session as default_factory

    factory = session_factory or default_factory
    totals = {"metrics": 0, "businesses": 0, "errors": 0}

    today = datetime.now(timezone.utc).date()
    cur_start = today - timedelta(days=_WINDOW_DAYS - 1)

    async with factory() as db:
        try:
            # Fetch all stored daily metrics in the window.
            rows = (
                await db.execute(
                    select(ChannelDailyMetric).where(
                        ChannelDailyMetric.date >= cur_start
                    )
                )
            ).scalars().all()

            if not rows:
                logger.info("Market benchmarks: no daily metrics in window")
                return totals

            # Group by metric across all tenants.
            # We compute per-tenant aggregates first, then cross-tenant stats.
            tenant_metrics: dict[str, dict[str, list[float]]] = {}
            for r in rows:
                tid = r.user_id
                if tid not in tenant_metrics:
                    tenant_metrics[tid] = {
                        "median_first_response_seconds": [],
                        "response_rate": [],
                        "messages_in": [],
                        "conversations_in": [],
                    }
                if r.median_first_response_seconds is not None:
                    tenant_metrics[tid]["median_first_response_seconds"].append(
                        float(r.median_first_response_seconds)
                    )
                convs = r.conversations_in or 0
                replied = r.conversations_replied or 0
                if convs > 0:
                    tenant_metrics[tid]["response_rate"].append(replied / convs * 100.0)
                tenant_metrics[tid]["messages_in"].append(float(r.messages_in or 0))
                tenant_metrics[tid]["conversations_in"].append(float(convs))

            totals["businesses"] = len(tenant_metrics)

            # Cross-tenant aggregates: one row per metric.
            metrics_to_compute = [
                ("median_first_response_seconds", "median_first_response_seconds"),
                ("response_rate", "response_rate"),
                ("messages_in", "messages_in"),
                ("conversations_in", "conversations_in"),
            ]

            for metric_name, key in metrics_to_compute:
                # One value per tenant (average of their daily values).
                tenant_values = []
                for tid, vals in tenant_metrics.items():
                    v = vals.get(key, [])
                    if v:
                        tenant_values.append(statistics.median(v))

                if not tenant_values:
                    continue

                tenant_values.sort()
                median_val = statistics.median(tenant_values)
                p25_val = _percentile(tenant_values, 0.25)
                p75_val = _percentile(tenant_values, 0.75)

                # Upsert.
                existing = (
                    await db.execute(
                        select(MarketBenchmark).where(
                            MarketBenchmark.date == today,
                            MarketBenchmark.scope_market == "global",
                            MarketBenchmark.scope_network == "all",
                            MarketBenchmark.metric == metric_name,
                        )
                    )
                ).scalar_one_or_none()

                if existing:
                    existing.median = median_val
                    existing.p25 = p25_val
                    existing.p75 = p75_val
                    existing.business_count = len(tenant_values)
                    existing.computed_at = datetime.now(timezone.utc)
                else:
                    row = MarketBenchmark(
                        date=today,
                        scope_market="global",
                        scope_network="all",
                        metric=metric_name,
                        median=median_val,
                        p25=p25_val,
                        p75=p75_val,
                        business_count=len(tenant_values),
                        computed_at=datetime.now(timezone.utc),
                    )
                    db.add(row)
                totals["metrics"] += 1

            await db.commit()
        except Exception as e:
            logger.error("Market benchmarks aggregation failed: %s", e)
            totals["errors"] += 1
            await db.rollback()

    return totals


async def run_market_benchmarks_worker() -> None:
    """Background loop. Runs aggregate_once daily."""
    interval = getattr(settings, "MARKET_BENCHMARKS_INTERVAL_SECONDS", 86400)
    logger.info("Market benchmarks worker started (interval=%ds)", interval)
    while True:
        try:
            totals = await aggregate_once()
            logger.info("Market benchmarks pass: %s", totals)
        except Exception as e:
            logger.error("Market benchmarks worker error: %s", e)
        await asyncio.sleep(interval)
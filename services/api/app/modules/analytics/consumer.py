"""Analytics Kafka consumer: review enrichment + daily rollup pipeline.

Event flow (everything persisted in PostgreSQL, streamed via Kafka through
the transactional outbox — modules/outbox):

    reviews_worker ──enqueue──▶ review.discovered ──▶ [this consumer]
                          │                                │  LLM enrich
                          │                                ▼
                          │                         review_insights (DB)
                          │                                │
                          └──enqueue──▶ review.enriched ◀──┘
                                             │
                                             ▼
                              location_daily_metrics rollup (DB)

Reply events (`review.replied`, emitted by the reviews worker) update the
replied flags so response-rate / response-time metrics stay accurate.

Kafka outages degrade gracefully: events stay "pending" in the outbox and
are retried by the outbox worker; this consumer simply keeps looping.
"""
import asyncio
import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from ...database import async_session
from ..channels.models import ReviewReply
from ..kafka.client import create_consumer
from ..outbox.service import enqueue_event
from .enrichment import enrich_review
from .models import LocationDailyMetric, ReviewInsight

logger = logging.getLogger(__name__)

TOPIC = "review-events"
GROUP_ID = "analytics-enricher"


def _iso_to_dt(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


async def _handle_discovered(payload: dict) -> None:
    """Upsert the review, run AI enrichment, persist, emit review.enriched."""
    channel_id = payload.get("channel_id", "")
    review_id = payload.get("review_id", "")
    if not channel_id or not review_id:
        return

    async with async_session() as db:
        existing = (
            await db.execute(
                select(ReviewInsight).where(
                    ReviewInsight.channel_id == channel_id,
                    ReviewInsight.review_id == review_id,
                )
            )
        ).scalar_one_or_none()

        if existing and existing.enrichment_status == "done":
            return  # idempotent replay

        insight = existing or ReviewInsight(
            id=str(uuid.uuid4()),
            channel_id=channel_id,
            review_id=review_id,
        )
        insight.user_id = payload.get("user_id", insight.user_id or "")
        insight.rating = int(payload.get("rating") or 1)
        insight.review_text = payload.get("text")
        insight.reviewer_name = payload.get("reviewer_name")
        insight.review_updated_at = _iso_to_dt(payload.get("review_updated_at"))

        result = await enrich_review(
            insight.rating, insight.review_text, insight.reviewer_name
        )
        insight.sentiment = result["sentiment"]
        insight.sentiment_score = result["sentiment_score"]
        insight.topics = result["topics"]
        insight.products = result["products"]
        insight.problems = result["problems"]
        insight.enrichment_status = "done"

        db.add(insight)
        await db.commit()

        bucket_date = (insight.review_updated_at or insight.created_at).date()

    await enqueue_event(
        "review.enriched",
        {
            "user_id": insight.user_id,
            "channel_id": channel_id,
            "review_id": review_id,
            "rating": insight.rating,
            "sentiment": insight.sentiment,
            "review_date": bucket_date.isoformat(),
        },
        topic=TOPIC,
    )


async def _handle_replied(payload: dict) -> None:
    """Mark the review as replied and refresh the daily rollup."""
    channel_id = payload.get("channel_id", "")
    review_id = payload.get("review_id", "")
    if not channel_id or not review_id:
        return

    replied_at = _iso_to_dt(payload.get("replied_at")) or datetime.now(timezone.utc)
    async with async_session() as db:
        insight = (
            await db.execute(
                select(ReviewInsight).where(
                    ReviewInsight.channel_id == channel_id,
                    ReviewInsight.review_id == review_id,
                )
            )
        ).scalar_one_or_none()
        if insight:
            insight.replied = True
            insight.replied_at = replied_at
            insight.enrichment_status = insight.enrichment_status or "pending"
            db.add(insight)
            await db.commit()
            bucket_date = (insight.review_updated_at or insight.created_at).date()
    if insight:
        await recompute_daily_rollup(channel_id, payload.get("user_id", ""), bucket_date)


async def recompute_daily_rollup(channel_id: str, user_id: str, bucket_date) -> None:
    """Rebuild one day's rollup row from source rows (idempotent, self-healing)."""
    day_start = datetime(bucket_date.year, bucket_date.month, bucket_date.day, tzinfo=timezone.utc)
    day_end = day_start + timedelta(days=1)

    async with async_session() as db:
        totals = (
            await db.execute(
                select(
                    func.count(ReviewInsight.id),
                    func.avg(ReviewInsight.rating),
                ).where(
                    ReviewInsight.channel_id == channel_id,
                    func.coalesce(ReviewInsight.review_updated_at, ReviewInsight.created_at) >= day_start,
                    func.coalesce(ReviewInsight.review_updated_at, ReviewInsight.created_at) < day_end,
                )
            )
        ).one()

        sentiment_counts = dict(
            (
                await db.execute(
                    select(ReviewInsight.sentiment, func.count())
                    .where(
                        ReviewInsight.channel_id == channel_id,
                        func.coalesce(ReviewInsight.review_updated_at, ReviewInsight.created_at) >= day_start,
                        func.coalesce(ReviewInsight.review_updated_at, ReviewInsight.created_at) < day_end,
                    )
                    .group_by(ReviewInsight.sentiment)
                )
            ).all()
        )

        reviews_count = totals[0] or 0
        avg_rating = round(float(totals[1] or 0.0), 2)

        # Replies posted for reviews of this day (join via review_id)
        review_ids = (
            await db.execute(
                select(ReviewInsight.review_id).where(
                    ReviewInsight.channel_id == channel_id,
                    func.coalesce(ReviewInsight.review_updated_at, ReviewInsight.created_at) >= day_start,
                    func.coalesce(ReviewInsight.review_updated_at, ReviewInsight.created_at) < day_end,
                    ReviewInsight.replied == True,  # noqa: E712
                )
            )
        ).scalars().all()
        replies_count = 0
        if review_ids:
            replies_count = (
                await db.execute(
                    select(func.count(ReviewReply.id)).where(
                        ReviewReply.review_id.in_(review_ids),
                        ReviewReply.status == "posted",
                    )
                )
            ).scalar() or 0

        row = (
            await db.execute(
                select(LocationDailyMetric).where(
                    LocationDailyMetric.channel_id == channel_id,
                    LocationDailyMetric.date == bucket_date,
                )
            )
        ).scalar_one_or_none()
        if not row:
            row = LocationDailyMetric(id=str(uuid.uuid4()), channel_id=channel_id)
        row.user_id = user_id or row.user_id
        row.date = bucket_date
        row.reviews_count = reviews_count
        row.avg_rating = avg_rating
        row.positive_count = sentiment_counts.get("positive", 0)
        row.neutral_count = sentiment_counts.get("neutral", 0)
        row.negative_count = sentiment_counts.get("negative", 0)
        row.replies_count = replies_count
        db.add(row)
        await db.commit()

    logger.debug(
        "Rollup %s/%s: %s reviews (avg %.2f)", channel_id, bucket_date, reviews_count, avg_rating
    )


async def _process_message(value: bytes | None) -> None:
    if value is None:
        return
    try:
        event = json.loads(value.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as e:
        logger.warning("Discarding malformed event: %s", e)
        return

    event_type = event.get("event_type", "")
    payload = event.get("payload", event)
    try:
        if event_type == "review.discovered":
            await _handle_discovered(payload)
        elif event_type == "review.enriched":
            data = payload
            bucket = data.get("review_date")
            if bucket:
                from datetime import date as date_cls

                year, month, day = (int(p) for p in bucket.split("-"))
                await recompute_daily_rollup(
                    data.get("channel_id", ""), data.get("user_id", ""), date_cls(year, month, day)
                )
        elif event_type == "review.replied":
            await _handle_replied(payload)
        else:
            logger.debug("Ignoring unrelated event type %r on %s", event_type, TOPIC)
    except Exception as e:
        logger.exception("Failed processing %s event: %s", event_type, e)


async def _drain_outbox_events() -> int:
    """Process review events directly from the outbox (Kafka-down fallback).

    The outbox is the DB-backed queue, so the pipeline keeps working with no
    Kafka running. Handlers are idempotent, so events that the outbox worker
    also delivers to Kafka later are safe to process twice. Returns count.
    """
    from ..outbox.models import EventOutbox
    from ..outbox.service import mark_failed, mark_sent

    async with async_session() as db:
        events = (
            await db.execute(
                select(EventOutbox)
                .where(
                    EventOutbox.topic == TOPIC,
                    EventOutbox.status.in_(["pending", "failed"]),
                    EventOutbox.attempts < 10,
                )
                .order_by(EventOutbox.created_at)
                .limit(100)
            )
        ).scalars().all()
        db.expunge_all()

    sent_ids: list[str] = []
    for event in events:
        try:
            await _process_message(
                json.dumps({"event_type": event.event_type, "payload": event.payload}).encode("utf-8")
            )
            sent_ids.append(event.id)
        except Exception as e:
            logger.warning("Outbox event %s failed: %s", event.id, e)
            await mark_failed(event.id, str(e))
    if sent_ids:
        await mark_sent(sent_ids)
    return len(sent_ids)


async def run_analytics_consumer() -> None:
    """Background loop started from app lifespan.

    Kafka-first: consumes `review-events` from Kafka when available. When
    Kafka is down, falls back to draining events straight from the DB outbox
    (no error spam — the outage is logged once), and switches back to Kafka
    automatically once the connection recovers.
    """
    from ..kafka import client as kafka_client

    fallback_logged = False
    while True:
        consumer = None
        try:
            if not kafka_client._kafka_available:
                if not fallback_logged:
                    logger.info(
                        "Kafka unavailable — analytics consumer draining review events from the DB outbox"
                    )
                    fallback_logged = True
                await _drain_outbox_events()
                await asyncio.sleep(3)
                continue

            fallback_logged = False
            consumer = await create_consumer(group_id=GROUP_ID, topics=[TOPIC])
            logger.info("Analytics consumer listening on %s", TOPIC)
            async for msg in consumer:
                await _process_message(msg.value)
        except asyncio.CancelledError:
            if consumer:
                await consumer.stop()
            raise
        except Exception:
            # Connection failed — flip the flag so the outbox fallback kicks
            # in until the outbox worker's reconnect loop restores Kafka.
            if not fallback_logged:
                logger.warning("Kafka connection failed — switching to outbox fallback")
                fallback_logged = True
            kafka_client.mark_kafka_unavailable()
            if consumer:
                try:
                    await consumer.stop()
                except Exception:
                    pass
            await asyncio.sleep(5)

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
from ..channels.models import Channel, ReviewReply
from ..kafka.client import create_consumer
from ..notifications.service import notify
from ..outbox.service import enqueue_event
from .enrichment import enrich_review
from .models import LocationDailyMetric, ReviewInsight

logger = logging.getLogger(__name__)

TOPIC = "review-events"
GROUP_ID = "analytics-enricher"


async def _channel_owner(db, channel_id: str) -> str | None:
    """Authoritative tenant for a channel. Kafka payloads are untrusted —
    anyone with topic access can forge user_id, so consumers re-resolve
    ownership from the DB and ignore the payload claim on mismatch."""
    row = (
        await db.execute(select(Channel.user_id).where(Channel.id == channel_id))
    ).scalar_one_or_none()
    return row


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
        # B3: the channel row — not the event payload — decides the tenant.
        # Unknown channel → drop (cannot attribute). Forged user_id → DB wins.
        owner = await _channel_owner(db, channel_id)
        if not owner:
            logger.warning("Dropping review.discovered for unknown channel %s", channel_id)
            return
        if payload.get("user_id") and payload["user_id"] != owner:
            logger.warning("Tenant mismatch on review.discovered: payload claims %s, "
                           "channel %s belongs to %s — using channel owner",
                           payload.get("user_id"), channel_id, owner)
        existing = (
            await db.execute(
                select(ReviewInsight).where(
                    ReviewInsight.channel_id == channel_id,
                    ReviewInsight.review_id == review_id,
                )
            )
        ).scalar_one_or_none()

        # Reviewers can edit their review after the first sync. The pollers
        # send no "edited" marker, so content comparison is the detector:
        # a rating change or a non-empty text change means an edit.
        new_rating = int(payload.get("rating") or 1)
        new_text = payload.get("text")
        content_changed = False
        already_edited = False
        if existing is not None:
            already_edited = bool(existing.edited)
            content_changed = (
                new_rating != existing.rating
                or (bool(existing.review_text) and (new_text or None) != (existing.review_text or None))
            )
            if existing.enrichment_status == "done" and not content_changed:
                return  # idempotent replay
            if content_changed and not existing.edited:
                # First detection — snapshot what we had on file.
                existing.previous_rating = existing.rating
                existing.previous_review_text = existing.review_text

        insight = existing or ReviewInsight(
            id=str(uuid.uuid4()),
            channel_id=channel_id,
            review_id=review_id,
        )
        insight.user_id = owner
        insight.rating = new_rating
        insight.review_text = new_text
        insight.reviewer_name = payload.get("reviewer_name")
        if not insight.reviewer_photo_url and payload.get("reviewer_photo_url"):
            insight.reviewer_photo_url = payload.get("reviewer_photo_url")
        insight.review_updated_at = _iso_to_dt(payload.get("review_updated_at"))

        if content_changed:
            insight.edited = True
            insight.edited_at = datetime.now(timezone.utc)
            if not already_edited and insight.user_id:
                reviewer = insight.reviewer_name or "A customer"
                if (
                    insight.previous_rating is not None
                    and insight.previous_rating != insight.rating
                ):
                    title = (
                        f"{reviewer} changed their rating "
                        f"★{insight.previous_rating} → ★{insight.rating}"
                    )
                else:
                    title = f"{reviewer} edited their ★{insight.rating} review"
                await notify(
                    db, insight.user_id, "review_edited",
                    title,
                    (insight.review_text or "(text removed)")[:160],
                    data={"review_id": review_id, "channel_id": channel_id,
                          "rating": insight.rating,
                          "previous_rating": insight.previous_rating},
                    href="/dashboard/reviews?tab=edited",
                )

        result = await enrich_review(
            insight.rating, insight.review_text, insight.reviewer_name,
            tenant_id=insight.user_id or None,
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
        # B3: attribute the rollup to the channel owner, never the payload.
        owner = await _channel_owner(db, channel_id)
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
            if payload.get("status") == "posted":
                # A reply went live on Google — if it was generated after a
                # reviewer edit, the edit has been addressed. Pending drafts
                # keep the flag until the merchant actually publishes.
                insight.edited = False
                insight.edited_at = None
                insight.previous_rating = None
                insight.previous_review_text = None
            insight.enrichment_status = insight.enrichment_status or "pending"
            db.add(insight)
            await db.commit()
            bucket_date = (insight.review_updated_at or insight.created_at).date()
    if insight:
        await recompute_daily_rollup(channel_id, owner or insight.user_id, bucket_date)


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
                # B3: resolve the owner from the channel; payload claim ignored.
                async with async_session() as _db:
                    _owner = await _channel_owner(_db, data.get("channel_id", ""))
                await recompute_daily_rollup(
                    data.get("channel_id", ""), _owner or data.get("user_id", ""),
                    date_cls(year, month, day)
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

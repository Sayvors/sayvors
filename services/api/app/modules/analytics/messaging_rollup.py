"""Messaging daily rollup worker.

The write path behind the analytics messaging section. One pass upserts
`channel_daily_metrics` for every active messaging channel (WhatsApp /
Instagram / Facebook — everything except Google reviews) for today and the
two prior days, so a reply that lands the morning after a late-night
question still counts toward the day the conversation started. Rows older
than the 2-day lookback freeze; a reply 3+ days later is honestly not
counted.

Day buckets are UTC — consistent with every other daily table. The
per-hour heatmap that reads `by_hour_in` will convert to the business's
timezone at render time.

Nothing here is on any request path: dashboard endpoints read the stored
rows (see `service.get_messaging_overview`), never this module.
"""
import asyncio
import logging
import math
import uuid
from datetime import date, datetime, timedelta, timezone
from statistics import median

from sqlalchemy import func, select

from ...config import settings
from ...database import async_session
from ..channels.models import Channel, ChannelComment, ChannelMessage
from .models import ChannelDailyMetric

logger = logging.getLogger(__name__)

# A conversation's reply window: each pass recomputes the last 2 days, so
# an FRT may straddle midnight by up to this much before it stops counting.
_LOOKBACK = timedelta(days=2)
# Cap on stored FRT samples per day. Real volumes sit in the dozens; the
# cap keeps a runaway day from bloating the row, thinned evenly so the
# shape of the distribution survives.
_MAX_SAMPLES = 500


def _utc(dt: datetime) -> datetime:
    """SQLite returns naive UTC datetimes; Postgres returns aware ones.
    Normalize before any comparison so both behave identically."""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _percentile(sorted_samples: list[int], q: float) -> int | None:
    """Nearest-rank percentile on a pre-sorted list (deterministic, no
    interpolation — with sample sizes this small the difference is noise)."""
    n = len(sorted_samples)
    if n == 0:
        return None
    k = min(n - 1, max(0, math.ceil(q * n) - 1))
    return int(sorted_samples[k])


def _thin(samples: list[int]) -> list[int]:
    samples = sorted(int(s) for s in samples)
    if len(samples) <= _MAX_SAMPLES:
        return samples
    step = math.ceil(len(samples) / _MAX_SAMPLES)
    return samples[::step]


async def rollup_channel_days(db, channel: Channel, days: list[date]) -> int:
    """Recompute the given days for one channel. Idempotent: an existing
    (channel_id, date) row is overwritten in place, never twinned.

    Returns the number of rows written.
    """
    now = datetime.now(timezone.utc)
    written = 0

    # First-ever inbound per contact — one group-by for the whole channel,
    # reused across the day rows (contacts_new = new customers, not new
    # messages from known ones).
    first_contact_rows = (
        await db.execute(
            select(ChannelMessage.contact_phone, func.min(ChannelMessage.created_at))
            .where(
                ChannelMessage.channel_id == channel.id,
                ChannelMessage.contact_phone.is_not(None),
                ChannelMessage.direction == "inbound",
            )
            .group_by(ChannelMessage.contact_phone)
        )
    ).all()
    first_contact_at = {phone: ts for phone, ts in first_contact_rows}

    for day in days:
        day_start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
        day_end = day_start + timedelta(days=1)
        # Replies and comment-answers may land after the day itself; look
        # ahead so the FRT is attributed to the day the customer spoke.
        window_end = min(day_end + _LOOKBACK, now)

        msgs = (
            await db.execute(
                select(ChannelMessage)
                .where(
                    ChannelMessage.channel_id == channel.id,
                    ChannelMessage.created_at >= day_start,
                    ChannelMessage.created_at < window_end,
                )
            )
        ).scalars().all()

        in_day = [m for m in msgs if _utc(m.created_at) < day_end]
        messages_in = sum(1 for m in in_day if m.direction == "inbound")
        messages_out = sum(1 for m in in_day if m.direction == "outbound")

        # Conversations keyed by platform addressing (contact_phone). Rows
        # with a NULL phone predate the column and stay out of conversation
        # metrics — their volume still counts above.
        convs: dict[str, list[ChannelMessage]] = {}
        for m in msgs:
            if m.contact_phone:
                convs.setdefault(m.contact_phone, []).append(m)

        samples: list[int] = []
        conversations_in = 0
        unanswered = 0
        oldest_unanswered: float | None = None
        for thread in convs.values():
            thread.sort(key=lambda m: _utc(m.created_at))
            day_inbounds = [
                m for m in thread
                if m.direction == "inbound" and _utc(m.created_at) < day_end
            ]
            if not day_inbounds:
                continue
            conversations_in += 1
            first_in = day_inbounds[0]
            reply = next(
                (
                    m for m in thread
                    if m.direction == "outbound" and _utc(m.created_at) >= _utc(first_in.created_at)
                ),
                None,
            )
            if reply is not None:
                samples.append((_utc(reply.created_at) - _utc(first_in.created_at)).total_seconds())
            elif day_start.date() == now.date():
                # Snapshot-only: unanswered is a NOW number, so it is stored
                # on today's row and stays NULL once the day freezes.
                unanswered += 1
                age = (now - _utc(first_in.created_at)).total_seconds()
                oldest_unanswered = age if oldest_unanswered is None else max(oldest_unanswered, age)

        samples = _thin(samples)

        # Comments: inbound volume + how many got a direct reply (the reply
        # may arrive inside the same 48h lookback window).
        comments = (
            await db.execute(
                select(ChannelComment)
                .where(
                    ChannelComment.channel_id == channel.id,
                    ChannelComment.created_at >= day_start,
                    ChannelComment.created_at < window_end,
                )
            )
        ).scalars().all()
        comments_in = sum(
            1 for c in comments
            if c.direction == "inbound" and _utc(c.created_at) < day_end
        )
        answered_parent_ids = {
            c.parent_platform_comment_id
            for c in comments
            if c.direction == "outbound" and c.parent_platform_comment_id
        }
        comments_replied = sum(
            1 for c in comments
            if c.direction == "inbound"
            and _utc(c.created_at) < day_end
            and c.platform_comment_id in answered_parent_ids
        )

        contacts_new = sum(
            1
            for ts in first_contact_at.values()
            if ts is not None and day_start <= _utc(ts) < day_end
        )

        by_hour = [0] * 24
        for m in in_day:
            if m.direction == "inbound":
                by_hour[_utc(m.created_at).hour] += 1

        row = (
            await db.execute(
                select(ChannelDailyMetric).where(
                    ChannelDailyMetric.channel_id == channel.id,
                    ChannelDailyMetric.date == day,
                )
            )
        ).scalar_one_or_none()
        if not row:
            row = ChannelDailyMetric(
                id=str(uuid.uuid4()),
                channel_id=channel.id,
                user_id=channel.user_id,
                date=day,
            )
        row.messages_in = messages_in
        row.messages_out = messages_out
        row.conversations_in = conversations_in
        row.conversations_replied = len(samples)
        row.median_first_response_seconds = (
            int(round(median(samples))) if samples else None
        )
        row.p90_first_response_seconds = _percentile(samples, 0.9)
        row.frt_samples = samples
        row.unanswered_open = unanswered if day_start.date() == now.date() else None
        row.oldest_unanswered_seconds = (
            int(oldest_unanswered) if oldest_unanswered is not None else None
        )
        row.comments_in = comments_in
        row.comments_replied = comments_replied
        row.contacts_new = contacts_new
        row.by_hour_in = by_hour
        row.computed_at = now
        db.add(row)
        written += 1

    await db.commit()
    return written


async def rollup_all() -> dict:
    """One pass over every active messaging channel. Returns totals."""
    today = datetime.now(timezone.utc).date()
    days = [today - timedelta(days=2), today - timedelta(days=1), today]
    totals = {"channels": 0, "rows": 0, "errors": 0}

    async with async_session() as db:
        channels = (
            await db.execute(
                select(Channel).where(
                    Channel.platform != "google_reviews",
                    Channel.status == "active",
                )
            )
        ).scalars().all()

        for channel in channels:
            totals["channels"] += 1
            try:
                totals["rows"] += await rollup_channel_days(db, channel, days)
            except Exception:
                logger.exception("Messaging rollup failed for channel %s", channel.id)
                totals["errors"] += 1

    if totals["channels"]:
        logger.info("Messaging rollup: %s", totals)
    return totals


async def run_messaging_rollup_worker() -> None:
    """Background loop started from app lifespan / the worker entrypoint."""
    interval = max(300, settings.MESSAGING_ROLLUP_INTERVAL_SECONDS)
    while True:
        try:
            await rollup_all()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.error("Messaging rollup pass failed: %s", e)
        await asyncio.sleep(interval)

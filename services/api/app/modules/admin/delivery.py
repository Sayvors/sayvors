"""Meta delivery reconciliation for the admin console.

WhatsApp/Instagram/Facebook do not expose a message-count API. The only
provider-side numbers are the per-message events we already ingest: webhook
``messages`` for inbound and ``statuses`` for outbound. This module reports
what Meta actually confirmed, separately from what our database holds, so an
operator can see the gap instead of assuming the two must match.

Deliberately two grouped queries (per channel and per day), both bounded by the
window and served by the outbound-status / channel-created indexes. No
per-message loop, so a tenant with millions of messages costs the same as one
with hundreds.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..channels.models import Channel, ChannelMessage

META_PLATFORMS = ("whatsapp", "instagram", "facebook")
MAX_DAYS = 365

# Statuses Meta can report for an outbound message. `sent` here means "Meta
# accepted the send, no delivery webhook yet" - which is exactly the number to
# watch when webhooks break.
_OUTBOUND_STATUSES = ("sent", "delivered", "read", "failed")


def _blank_bucket() -> dict:
    return {
        "inbound": 0,
        "outbound": 0,
        "outbound_with_id": 0,
        "outbound_without_id": 0,
        "sent": 0,
        "delivered": 0,
        "read": 0,
        "failed": 0,
    }


def _add(bucket: dict, direction: str, status: str, total: int, with_id: int) -> None:
    if direction == "inbound":
        bucket["inbound"] += total
        return
    bucket["outbound"] += total
    bucket["outbound_with_id"] += with_id
    bucket["outbound_without_id"] += total - with_id
    if status in _OUTBOUND_STATUSES:
        bucket[status] += total


def _finish(bucket: dict) -> dict:
    confirmed = bucket["delivered"] + bucket["read"]
    return {
        **bucket,
        "delivery_rate_pct": (
            round(100 * confirmed / bucket["outbound_with_id"], 1)
            if bucket["outbound_with_id"]
            else None
        ),
    }


async def get_delivery_reconciliation(
    db: AsyncSession, tenant_id: str, days: int = 30
) -> dict:
    days = max(1, min(int(days or 30), MAX_DAYS))
    since = datetime.now(timezone.utc) - timedelta(days=days)
    channels = (
        await db.execute(
            select(Channel)
            .where(
                Channel.user_id == tenant_id,
                Channel.platform.in_(META_PLATFORMS),
            )
            .order_by(Channel.created_at)
        )
    ).scalars().all()
    channel_ids = [c.id for c in channels]
    channel_by_id = {
        c.id: {
            "channel_id": c.id,
            "name": c.display_name or c.id,
            "platform": c.platform,
            "status": c.status,
        }
        for c in channels
    }

    result: dict = {
        "days": days,
        "window_start": since.isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "platforms": sorted({c.platform for c in channels}),
        "totals": _finish(_blank_bucket()),
        "by_channel": [],
        "daily": [],
        "notes": [
            "Meta has no message-count API. These are the messages and statuses "
            "Meta actually delivered to our webhook.",
            "A message counted here but missing from Meta's conversation "
            "analytics is expected: Meta bills 24-hour conversations, not "
            "messages.",
            "outbound_without_id = sends that never reached Meta (validation "
            "or transport failure).",
        ],
    }
    if not channel_ids:
        return result

    window = [
        ChannelMessage.channel_id.in_(channel_ids),
        ChannelMessage.created_at >= since,
    ]

    # 1) Per channel + direction + status.
    per_channel_rows = (
        await db.execute(
            select(
                ChannelMessage.channel_id,
                ChannelMessage.direction,
                ChannelMessage.status,
                func.count().label("total"),
                func.count(func.nullif(ChannelMessage.platform_message_id, "")).label("with_id"),
            )
            .where(*window)
            .group_by(ChannelMessage.channel_id, ChannelMessage.direction, ChannelMessage.status)
        )
    ).all()

    buckets: dict[str, dict] = {}
    totals = _blank_bucket()
    for channel_id, direction, status, total, with_id in per_channel_rows:
        bucket = buckets.setdefault(channel_id, _blank_bucket())
        _add(bucket, str(direction), str(status), int(total), int(with_id))
        _add(totals, str(direction), str(status), int(total), int(with_id))

    result["totals"] = _finish(totals)
    result["by_channel"] = [
        {**channel_by_id[channel_id], **_finish(bucket)}
        for channel_id, bucket in sorted(
            buckets.items(),
            key=lambda item: item[1]["outbound"],
            reverse=True,
        )
        if channel_id in channel_by_id
    ]

    # 2) Daily series, same window. `date()` exists on Postgres and SQLite, so
    # the query works in tests without a dialect branch.
    day = func.date(ChannelMessage.created_at)
    daily_rows = (
        await db.execute(
            select(
                day.label("day"),
                ChannelMessage.direction,
                ChannelMessage.status,
                func.count().label("total"),
                func.count(func.nullif(ChannelMessage.platform_message_id, "")).label("with_id"),
            )
            .where(*window)
            .group_by(day, ChannelMessage.direction, ChannelMessage.status)
            .order_by(day)
        )
    ).all()
    daily: dict[str, dict] = {}
    for day_value, direction, status, total, with_id in daily_rows:
        key = str(day_value)[:10]
        bucket = daily.setdefault(key, _blank_bucket())
        _add(bucket, str(direction), str(status), int(total), int(with_id))
    result["daily"] = [
        {"day": key, **_finish(bucket)} for key, bucket in sorted(daily.items())
    ]
    return result

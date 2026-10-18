"""Windowed platform stats for the redesigned Overview page.

Read-only COUNTs against source tables (never the worker-fed daily rollups —
those lag by design). Direct SQL was chosen over Redis/Kafka counters: every
table here carries a created_at, and an admin dashboard's request rate is a
rounding error next to the drift risk of a second source of truth.
"""
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..analytics.models import ReviewInsight
from ..channels.models import Channel, ChannelMessage
from ..localith.models import LocalithConnection
from ..posts.models import LocationPost
from ..users.models import User

# Window slugs /overview/stats accepts (the router validates the pattern).
WINDOW_DELTAS: dict[str, timedelta] = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
    "90d": timedelta(days=90),
    "1y": timedelta(days=365),
}

# Backend-owned display labels, so enum drift never needs a frontend change.
PLATFORM_LABELS: dict[str, str] = {
    "whatsapp": "WhatsApp",
    "facebook": "Facebook",
    "instagram": "Instagram",
    "x": "X",
    "telegram": "Telegram",
    "linkedin": "LinkedIn",
    "google_reviews": "Google Reviews",
}


async def _count(db: AsyncSession, stmt) -> int:
    return (await db.execute(stmt)).scalar() or 0


def _platform_row(platform: str) -> dict:
    return {
        "platform": platform,
        "label": PLATFORM_LABELS.get(platform) or platform.replace("_", " ").title(),
        "connected": 0,
        "connected_total": 0,
        "messages": 0,
        "messages_in": 0,
        "messages_out": 0,
    }


async def _message_split(db: AsyncSession, since: datetime) -> tuple[int, int, int]:
    """(total, inbound, outbound) since `since` — one grouped query."""
    rows = (
        await db.execute(
            select(ChannelMessage.direction, func.count())
            .select_from(ChannelMessage)
            .where(ChannelMessage.created_at >= since)
            .group_by(ChannelMessage.direction)
        )
    ).all()
    by_dir = {direction: n for direction, n in rows}
    return sum(by_dir.values()), by_dir.get("inbound", 0), by_dir.get("outbound", 0)


async def _ai_replies(db: AsyncSession, since: datetime) -> int:
    return await _count(
        db,
        select(func.count())
        .select_from(ChannelMessage)
        .where(
            ChannelMessage.created_at >= since,
            ChannelMessage.direction == "outbound",
            ChannelMessage.is_ai == True,  # noqa: E712 — SQLAlchemy idiom
        ),
    )


async def _platform_rows(db: AsyncSession, since: datetime) -> list[dict]:
    """Connected counts (all-time, by status) + message volume (window)."""
    # Known platforms first, zero-seeded, so the panel always renders 7 rows;
    # anything unexpected in the DB appends itself via setdefault.
    platforms: dict[str, dict] = {slug: _platform_row(slug) for slug in PLATFORM_LABELS}

    conn_rows = (
        await db.execute(
            select(Channel.platform, Channel.status, func.count()).group_by(
                Channel.platform, Channel.status
            )
        )
    ).all()
    for platform, status, n in conn_rows:
        row = platforms.setdefault(platform, _platform_row(platform))
        row["connected_total"] += n
        if status == "active":
            row["connected"] += n

    msg_rows = (
        await db.execute(
            select(Channel.platform, ChannelMessage.direction, func.count())
            .select_from(ChannelMessage)
            .join(Channel, ChannelMessage.channel_id == Channel.id)
            .where(ChannelMessage.created_at >= since)
            .group_by(Channel.platform, ChannelMessage.direction)
        )
    ).all()
    for platform, direction, n in msg_rows:
        row = platforms.setdefault(platform, _platform_row(platform))
        row["messages"] += n
        if direction == "inbound":
            row["messages_in"] += n
        else:
            row["messages_out"] += n

    return list(platforms.values())


async def _window_counts(db: AsyncSession, since: datetime) -> dict:
    """Everything that happened in [since, now)."""
    owner = or_(User.tenant_id.is_(None), User.tenant_id == User.id)
    users = await _count(
        db, select(func.count()).select_from(User).where(User.created_at >= since)
    )
    tenants = await _count(
        db, select(func.count()).select_from(User).where(owner, User.created_at >= since)
    )
    businesses = await _count(
        db,
        select(func.count())
        .select_from(LocalithConnection)
        .where(LocalithConnection.created_at >= since),
    )
    reviews = await _count(
        db,
        select(func.count())
        .select_from(ReviewInsight)
        .where(ReviewInsight.created_at >= since),
    )
    messages, messages_in, messages_out = await _message_split(db, since)
    posts = await _count(
        db,
        select(func.count())
        .select_from(LocationPost)
        .where(LocationPost.created_at >= since),
    )
    return {
        "users": users,
        "tenants": tenants,
        "businesses": businesses,
        "reviews": reviews,
        "messages": messages,
        "messages_in": messages_in,
        "messages_out": messages_out,
        "ai_replies": await _ai_replies(db, since),
        "posts": posts,
    }


def _iso(dt: datetime) -> str:
    return dt.isoformat()


async def get_stats(db: AsyncSession, window: str = "30d") -> dict:
    """Totals + windowed deltas + per-platform + fixed last-24h, one payload."""
    now = datetime.now(timezone.utc)
    since = now - WINDOW_DELTAS.get(window, WINDOW_DELTAS["30d"])
    since_24h = now - WINDOW_DELTAS["24h"]

    owner = or_(User.tenant_id.is_(None), User.tenant_id == User.id)
    totals = {
        "users": await _count(db, select(func.count()).select_from(User)),
        "tenants": await _count(
            db, select(func.count()).select_from(User).where(owner)
        ),
        "businesses": await _count(
            db, select(func.count()).select_from(LocalithConnection)
        ),
        "reviews": await _count(db, select(func.count()).select_from(ReviewInsight)),
        "messages": await _count(db, select(func.count()).select_from(ChannelMessage)),
        "posts": await _count(db, select(func.count()).select_from(LocationPost)),
    }

    window_delta = await _window_counts(db, since)
    # The 24h card is fixed at now-24h regardless of the selected window.
    if since == since_24h:
        last_24h = window_delta
    else:
        last_24h = await _window_counts(db, since_24h)

    return {
        "window": window,
        "window_start": _iso(since),
        "generated_at": _iso(now),
        "totals": totals,
        "window_delta": window_delta,
        "last_24h": {
            key: last_24h[key]
            for key in ("users", "reviews", "messages", "messages_in", "messages_out", "ai_replies")
        },
        "platforms": await _platform_rows(db, since),
    }


async def get_live_stats(db: AsyncSession, minutes: int = 30) -> dict:
    """Tiny payload for the 15s-polling live card (~6 cheap COUNTs)."""
    now = datetime.now(timezone.utc)
    since = now - timedelta(minutes=minutes)

    messages, messages_in, messages_out = await _message_split(db, since)

    volume_rows = (
        await db.execute(
            select(Channel.platform, func.count())
            .select_from(ChannelMessage)
            .join(Channel, ChannelMessage.channel_id == Channel.id)
            .where(ChannelMessage.created_at >= since)
            .group_by(Channel.platform)
        )
    ).all()
    top = max(volume_rows, key=lambda row: row[1]) if volume_rows else None

    # Connection state is "right now", not windowed: healthy listings vs
    # disabled/suspended ones.
    total_businesses = await _count(db, select(func.count()).select_from(LocalithConnection))
    businesses_down = await _count(
        db,
        select(func.count())
        .select_from(LocalithConnection)
        .where(
            or_(
                LocalithConnection.is_disabled == True,  # noqa: E712
                LocalithConnection.is_suspended == True,  # noqa: E712
            )
        ),
    )

    return {
        "minutes": minutes,
        "generated_at": _iso(now),
        "messages": messages,
        "messages_in": messages_in,
        "messages_out": messages_out,
        "ai_replies": await _ai_replies(db, since),
        "new_users": await _count(
            db, select(func.count()).select_from(User).where(User.created_at >= since)
        ),
        "new_reviews": await _count(
            db,
            select(func.count())
            .select_from(ReviewInsight)
            .where(ReviewInsight.created_at >= since),
        ),
        "businesses_connected": total_businesses - businesses_down,
        "businesses_disconnected": businesses_down,
        "active_platforms": len(volume_rows),
        "top_platform": top[0] if top else None,
    }

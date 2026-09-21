"""Profile service: PostgreSQL source of truth, Redis cache, Kafka events.

Read path:  GET /profile      -> Redis `profile:{uid}` (300s TTL) -> DB fallback
            GET /profile/usage -> Redis `usage:{uid}` (60s TTL) -> DB counts
Write path: PATCH             -> DB commit -> Redis invalidate -> outbox enqueue
            (outbox worker delivers to Kafka `auth-events`, retries on outage)
"""

import json
import logging
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..users.models import User
from .models import UserFeedback

logger = logging.getLogger(__name__)

PROFILE_TTL = 300
USAGE_TTL = 60

FEEDBACK_CATEGORIES = {"overall", "ai", "ui", "support", "value"}


def _profile_key(user_id: str) -> str:
    return f"profile:{user_id}"


async def _emit(
    event_type: str,
    user_id: str,
    email: str | None = None,
    metadata: dict | None = None,
) -> None:
    """Enqueue a Kafka-bound event using the standard auth-events envelope.

    Same shape as auth.events.log_auth_event so every record on the topic
    carries event_type + timestamp inside the value (keys aren't shown by
    plain console consumers and shouldn't be the only type signal).
    Envelope is built inline to avoid importing the auth package (its
    __init__ pulls in the router).
    """
    from datetime import datetime, timezone

    try:
        from ..outbox.service import enqueue_event

        await enqueue_event(
            event_type=event_type,
            payload={
                "event_type": event_type,
                "user_id": user_id,
                "email": email,
                "ip_address": None,
                "user_agent": None,
                "success": True,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "metadata": metadata or {},
            },
            topic="auth-events",
        )
    except Exception:
        logger.exception("Failed to enqueue %s", event_type)


def _usage_key(user_id: str) -> str:
    return f"usage:{user_id}"


async def _cache_get(key: str) -> dict | None:
    try:
        from ..redis.client import get_redis

        redis = await get_redis()
        raw = await redis.get(key)
        return json.loads(raw) if raw else None
    except Exception:
        return None


async def _cache_set(key: str, value: dict, ttl: int) -> None:
    try:
        from ..redis.client import get_redis

        redis = await get_redis()
        await redis.setex(key, ttl, json.dumps(value, default=str))
    except Exception:
        pass


async def _cache_delete(*keys: str) -> None:
    try:
        from ..redis.client import get_redis

        redis = await get_redis()
        if keys:
            await redis.delete(*keys)
    except Exception:
        pass


def _serialize(user: User, feedback: dict[str, int]) -> dict:
    created = user.created_at
    if isinstance(created, datetime):
        member_since = created.isoformat()
    else:
        member_since = str(created)
    return {
        "id": user.id,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "email": user.email,
        "email_verified": user.email_verified,
        "onboarded": user.onboarded,
        "bio": user.bio,
        "business_name": user.business_name,
        "business_type": user.business_type,
        "business_sells": user.business_sells,
        "business_doesnt_sell": user.business_doesnt_sell,
        "business_description": user.business_description,
        "phone": user.phone,
        "country": user.country,
        "theme": user.theme or "light",
        "language": user.language or "en",
        "plan": "pro",
        "member_since": member_since,
        "feedback": feedback,
    }


async def get_profile(user_id: str, db: AsyncSession) -> dict:
    cached = await _cache_get(_profile_key(user_id))
    if cached:
        return cached

    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise ValueError("User not found")

    rows = (
        await db.execute(select(UserFeedback).where(UserFeedback.user_id == user_id))
    ).scalars().all()
    feedback = {r.category: r.stars for r in rows}

    payload = _serialize(user, feedback)
    await _cache_set(_profile_key(user_id), payload, PROFILE_TTL)
    return payload


async def update_profile(user_id: str, data: dict, db: AsyncSession) -> dict:
    allowed = {"first_name", "last_name", "bio", "business_name", "business_type",
               "business_sells", "business_doesnt_sell", "business_description",
               "phone", "country"}
    patch = {k: v for k, v in data.items() if k in allowed and v is not None}
    if not patch:
        raise ValueError("No valid fields to update")

    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise ValueError("User not found")
    for field, value in patch.items():
        setattr(user, field, value)
    user.updated_at = datetime.now(timezone.utc)
    db.add(user)
    await db.commit()

    await _cache_delete(_profile_key(user_id), _usage_key(user_id))

    await _emit(
        "profile.updated",
        user_id,
        email=user.email,
        metadata={"fields": sorted(patch.keys())},
    )

    return await get_profile(user_id, db)


async def update_preferences(user_id: str, theme: str, language: str, db: AsyncSession) -> dict:
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise ValueError("User not found")
    user.theme = theme
    user.language = language
    user.updated_at = datetime.now(timezone.utc)
    db.add(user)
    await db.commit()

    await _cache_delete(_profile_key(user_id))

    await _emit(
        "preferences.updated",
        user_id,
        email=user.email,
        metadata={"theme": theme, "language": language},
    )

    return await get_profile(user_id, db)


async def get_usage(user_id: str, db: AsyncSession) -> dict:
    cached = await _cache_get(_usage_key(user_id))
    if cached:
        return {**cached, "cached": True}

    from ..channels.models import Channel
    from ..rag.models import Databank, Document

    databanks = (await db.execute(select(func.count()).where(Databank.user_id == user_id))).scalar() or 0
    documents = (await db.execute(select(func.count()).where(Document.user_id == user_id))).scalar() or 0
    channels = (await db.execute(select(func.count()).where(Channel.user_id == user_id))).scalar() or 0
    feedback_count = (
        await db.execute(select(func.count()).where(UserFeedback.user_id == user_id))
    ).scalar() or 0

    payload = {
        "items": [
            {"label": "Databanks", "used": databanks, "total": 10, "unit": "databanks",
             "percent": round(min(databanks / 10, 1) * 100, 1)},
            {"label": "Documents", "used": documents, "total": 100, "unit": "documents",
             "percent": round(min(documents / 100, 1) * 100, 1)},
            {"label": "Channels Connected", "used": channels, "total": 7, "unit": "channels",
             "percent": round(min(channels / 7, 1) * 100, 1)},
            {"label": "Feedback Given", "used": feedback_count, "total": 5, "unit": "categories",
             "percent": round(min(feedback_count / 5, 1) * 100, 1)},
        ],
        "cached": False,
    }
    await _cache_set(_usage_key(user_id), payload, USAGE_TTL)
    return payload


async def list_feedback(user_id: str, db: AsyncSession) -> dict[str, int]:
    rows = (
        await db.execute(select(UserFeedback).where(UserFeedback.user_id == user_id))
    ).scalars().all()
    return {r.category: r.stars for r in rows}


async def submit_feedback(user_id: str, category: str, stars: int, db: AsyncSession) -> dict[str, int]:
    category = category.strip().lower()
    if category not in FEEDBACK_CATEGORIES:
        raise ValueError(f"Unknown category. Use one of: {sorted(FEEDBACK_CATEGORIES)}")

    row = (
        await db.execute(
            select(UserFeedback).where(
                UserFeedback.user_id == user_id, UserFeedback.category == category
            )
        )
    ).scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if row:
        row.stars = stars
        row.updated_at = now
    else:
        row = UserFeedback(user_id=user_id, category=category, stars=stars)
        db.add(row)
    await db.commit()

    await _cache_delete(_profile_key(user_id), _usage_key(user_id))

    await _emit(
        "feedback.submitted",
        user_id,
        metadata={"category": category, "stars": stars},
    )

    return await list_feedback(user_id, db)


async def get_business_context(user_id: str | None, db) -> dict:
    """Tenant-owned AI-grounding facts: category, sells, doesn't-sell, blurb.

    Never raises — AI paths must survive a missing user/table. Returns {}
    when there is nothing configured so callers can distinguish "no facts"
    from "no user".

    The probe runs inside a SAVEPOINT: a failure (e.g. column missing on a
    DB that hasn't migrated) rolls back only the savepoint, never the
    caller's session — otherwise the aborted transaction (Postgres) or the
    expiry from a session rollback would break every later ORM access with
    MissingGreenlet.
    """
    if not user_id:
        return {}
    try:
        async with db.begin_nested():
            user = (
                await db.execute(select(User).where(User.id == user_id))
            ).scalar_one_or_none()
    except Exception:
        return {}
    if not user:
        return {}
    ctx = {
        "business_name": (getattr(user, "business_name", None) or "").strip(),
        "business_type": (getattr(user, "business_type", None) or "").strip(),
        "business_sells": (getattr(user, "business_sells", None) or "").strip(),
        "business_doesnt_sell": (
            getattr(user, "business_doesnt_sell", None) or ""
        ).strip(),
        "business_description": (
            getattr(user, "business_description", None) or ""
        ).strip(),
    }
    return {k: v for k, v in ctx.items() if v}


def format_business_identity(ctx: dict | None, services: list[str] | None = None) -> str:
    """Render business context as a prompt-ready identity block.

    Owner-configured facts — the model must treat them as ground truth and
    never contradict them (they outrank anything the reviewer claims).
    `services` is the owner's offered-services list (Services page);
    appended as its own line. Returns "" when there is nothing configured.
    """
    if not ctx:
        ctx = {}
    lines = ["Business identity (owner-configured facts — treat as ground truth):"]
    name = ctx.get("business_name") or ""
    btype = ctx.get("business_type") or ""
    who = " ".join(p for p in [name, f"({btype})" if btype else ""] if p).strip()
    if who:
        lines.append(f"- Business: {who}")
    elif btype:
        lines.append(f"- Business type: {btype}")
    if ctx.get("business_sells"):
        lines.append(f"- Sells / offers: {ctx['business_sells'][:500]}")
    if services:
        lines.append(
            "- Services offered (from the owner's Services page — treat as "
            f"ground truth): {', '.join(services)[:800]}"
        )
    if ctx.get("business_doesnt_sell"):
        lines.append(
            "- Does NOT sell (never claim otherwise, never apologize for "
            f"not carrying these): {ctx['business_doesnt_sell'][:500]}"
        )
    if ctx.get("business_description"):
        lines.append(f"- About: {ctx['business_description'][:500]}")
    return "\n".join(lines) if len(lines) > 1 else ""


async def get_offered_services(
    user_id: str | None, db, channel_id: str | None = None, limit: int = 20
) -> list[str]:
    """Names of services the tenant offers (channel-scoped when given).

    Reads the same channel_services rows the owner toggles on the Services
    page — the AI treats them as ground truth beside sells/does-not-sell.
    Never raises. Savepoint-isolated like get_business_context: a probe
    failure must never poison the caller's session.
    """
    if not user_id:
        return []
    try:
        from sqlalchemy import select

        from ..channels.models import BusinessService, Channel

        stmt = (
            select(BusinessService.name, BusinessService.category)
            .join(Channel, Channel.id == BusinessService.channel_id)
            .where(
                Channel.user_id == user_id,
                BusinessService.is_offered.is_(True),
            )
            .order_by(BusinessService.name)
            .limit(limit)
        )
        if channel_id:
            stmt = stmt.where(BusinessService.channel_id == channel_id)
        async with db.begin_nested():
            rows = (await db.execute(stmt)).all()
    except Exception:
        return []
    names: list[str] = []
    for name, category in rows:
        label = (name or "").strip()
        if not label:
            continue
        cat = (category or "").strip()
        if cat and cat.lower() not in ("custom", label.lower()):
            label = f"{label} ({cat})"
        if label not in names:
            names.append(label)
    return names

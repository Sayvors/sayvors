"""Profile service: PostgreSQL source of truth, Redis cache, Kafka events.

Read path:  GET /profile      -> Redis `profile:{uid}` (300s TTL) -> DB fallback
            GET /profile/usage -> Redis `usage:{uid}` (60s TTL) -> DB counts
Write path: PATCH             -> DB commit -> Redis invalidate -> outbox enqueue
            (outbox worker delivers to Kafka `auth-events`, retries on outage)
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..users.models import User
from .models import UserFeedback

logger = logging.getLogger(__name__)

PROFILE_TTL = 300
USAGE_TTL = 60

FEEDBACK_CATEGORIES = {"overall", "ai", "ui", "support", "value"}

# A profile picture is rendered at 96-160 CSS px; 8 MB is already generous
# for a phone photo and keeps a public object from becoming a bandwidth sink.
AVATAR_MAX_BYTES = 8 * 1024 * 1024
COVER_MAX_BYTES = 12 * 1024 * 1024

# SVG is deliberately absent: it is an executable document, and these objects
# are served from a public URL. Raster formats only.
_IMAGE_TYPES: dict[str, str] = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}

AVATAR_SOURCES = {"google", "facebook", "upload", "none"}
_AVATAR_FIELDS = {
    "google": "google_avatar_url",
    "facebook": "facebook_avatar_url",
    "upload": "avatar_upload_url",
}


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
        "avatar_url": user.avatar_url,
        "avatar_source": user.avatar_source,
        "google_avatar_url": user.google_avatar_url,
        "facebook_avatar_url": user.facebook_avatar_url,
        "avatar_upload_url": user.avatar_upload_url,
        "cover_url": user.cover_url,
        "google_connected": bool(user.google_sub),
        "facebook_connected": bool(user.facebook_id),
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
        "response_style": getattr(user, "response_style", None) or "concise",
        "voice_replies": getattr(user, "voice_replies", None) or "off",
        # getattr default keeps the response correct on a row written before
        # the column existed; the migration's server_default covers the rest.
        "typing_indicator": (
            True if getattr(user, "typing_indicator", None) is None
            else bool(user.typing_indicator)
        ),
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
    feedback = [{"emoji_rating": r.emoji_rating, "message": r.message, "created_at": r.created_at.isoformat() if r.created_at else None} for r in rows]

    payload = _serialize(user, feedback)
    await _cache_set(_profile_key(user_id), payload, PROFILE_TTL)
    return payload


async def update_profile(user_id: str, data: dict, db: AsyncSession) -> dict:
    # A PATCH may clear a nullable field by sending an explicit null ("Not set"
    # in the account form). Names are required, so a null there is dropped
    # rather than reaching a NOT NULL column.
    clearable = {
        "bio", "business_name", "business_type", "business_sells",
        "business_doesnt_sell", "business_description", "phone", "country",
    }
    allowed = {"first_name", "last_name"} | clearable
    patch = {
        k: v
        for k, v in data.items()
        if k in allowed and (v is not None or k in clearable)
    }
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


async def _locked_user(user_id: str, db: AsyncSession) -> User:
    """Load the user with a row lock so two uploads cannot race.

    Without the lock two concurrent requests both read the previous storage
    key and both commit; the object superseded by the second write is then
    leaked forever. SQLite (tests) has no row locks and ignores the clause,
    which is correct for a single-writer test database.
    """
    user = (
        await db.execute(select(User).where(User.id == user_id).with_for_update())
    ).scalar_one_or_none()
    if not user:
        raise ValueError("User not found")
    return user


def _image_extension(filename: str, content_type: str | None) -> tuple[str, str]:
    ext = Path(filename or "").suffix.lower()
    expected = _IMAGE_TYPES.get(ext)
    if expected is None:
        raise ValueError("Use a JPG, PNG or WEBP image.")
    if content_type and not content_type.startswith("image/"):
        raise ValueError("Only image files are accepted.")
    return ext, expected


def _looks_like_image(ext: str, data: bytes) -> bool:
    """Reject a renamed non-image before it reaches a public bucket.

    The client's Content-Type is attacker-controlled; the bytes are not.
    """
    if ext in (".jpg", ".jpeg"):
        return data.startswith(b"\xff\xd8\xff")
    if ext == ".png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if ext == ".webp":
        return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    return False


def _delete_media_best_effort(user_id: str, storage_key: str) -> None:
    """Delete a superseded object without failing the user's save.

    The row already points at the replacement; a storage hiccup here costs one
    orphaned object, not a broken profile.
    """
    try:
        from ...core.storage import delete_media

        delete_media(user_id, storage_key)
    except Exception:
        logger.warning(
            "Could not delete superseded profile media %s for user %s",
            storage_key,
            user_id,
            exc_info=True,
        )


async def save_profile_image(
    user_id: str,
    kind: str,
    filename: str,
    content_type: str | None,
    data: bytes,
    base_url: str,
    db: AsyncSession,
) -> dict:
    """Store an uploaded avatar or cover and make it the effective image.

    `kind` is "avatar" or "cover". The stored content type is derived from the
    validated extension, never from the request header.
    """
    if kind not in {"avatar", "cover"}:
        raise ValueError("Unknown profile image kind.")
    max_bytes = AVATAR_MAX_BYTES if kind == "avatar" else COVER_MAX_BYTES
    if not data:
        raise ValueError("Empty file.")
    if len(data) > max_bytes:
        raise ValueError(f"File is too big — max {max_bytes // (1024 * 1024)}MB.")
    ext, expected_type = _image_extension(filename, content_type)
    if not _looks_like_image(ext, data):
        raise ValueError("File content doesn't look like the image type it claims.")

    from ...core.storage import local_media_url, put_media

    user = await _locked_user(user_id, db)
    storage_key, public_url = put_media(user_id, filename, data, expected_type)
    if not public_url:
        # Local backend has no origin of its own; the request supplies it so
        # the browser and the API resolve the same public URL.
        public_url = local_media_url(base_url, user_id, storage_key)

    if kind == "avatar":
        old_key = user.avatar_storage_key
        user.avatar_upload_url = public_url[:1000]
        user.avatar_storage_key = storage_key[:500]
        user.avatar_source = "upload"
        user.avatar_url = public_url[:1000]
        event = "avatar.updated"
    else:
        old_key = user.cover_storage_key
        user.cover_url = public_url[:1000]
        user.cover_storage_key = storage_key[:500]
        event = "cover.updated"

    user.updated_at = datetime.now(timezone.utc)
    db.add(user)
    await db.commit()

    if old_key and old_key != storage_key:
        _delete_media_best_effort(user_id, old_key)

    await _cache_delete(_profile_key(user_id))
    await _emit(event, user_id, email=user.email, metadata={"kind": kind})
    return await get_profile(user_id, db)


async def update_avatar_source(user_id: str, source: str, db: AsyncSession) -> dict:
    """Switch the effective avatar to a stored Google/Facebook/upload URL.

    "none" clears the picture but keeps every snapshot, so switching back is
    one click and never requires another OAuth round-trip.
    """
    if source not in AVATAR_SOURCES:
        raise ValueError("Unknown avatar source.")
    user = await _locked_user(user_id, db)

    if source == "none":
        user.avatar_source = "none"
        user.avatar_url = None
    else:
        url = getattr(user, _AVATAR_FIELDS[source])
        if not url:
            raise ValueError(
                "That picture is not available yet — sign in with the provider "
                "or upload one from your device."
            )
        user.avatar_source = source
        user.avatar_url = url[:1000]

    user.updated_at = datetime.now(timezone.utc)
    db.add(user)
    await db.commit()

    await _cache_delete(_profile_key(user_id))
    await _emit("avatar.source_updated", user_id, email=user.email,
                metadata={"source": source})
    return await get_profile(user_id, db)


async def remove_cover(user_id: str, db: AsyncSession) -> dict:
    """Clear the cover image and delete its stored object."""
    user = await _locked_user(user_id, db)
    old_key = user.cover_storage_key
    user.cover_url = None
    user.cover_storage_key = None
    user.updated_at = datetime.now(timezone.utc)
    db.add(user)
    await db.commit()

    if old_key:
        _delete_media_best_effort(user_id, old_key)

    await _cache_delete(_profile_key(user_id))
    await _emit("cover.removed", user_id, email=user.email)
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


async def update_response_style(user_id: str, response_style: str, db: AsyncSession) -> dict:
    """Persist the tenant's WhatsApp response style (same write path as
    preferences: DB commit -> cache invalidate -> outbox event)."""
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise ValueError("User not found")
    user.response_style = response_style
    user.updated_at = datetime.now(timezone.utc)
    db.add(user)
    await db.commit()

    await _cache_delete(_profile_key(user_id))

    await _emit(
        "response_style.updated",
        user_id,
        email=user.email,
        metadata={"response_style": response_style},
    )

    return await get_profile(user_id, db)


async def update_voice_replies(user_id: str, voice_replies: str, db: AsyncSession) -> dict:
    """Persist the tenant's WhatsApp voice replies tier (same write path as
    preferences). The engine behind each tier is admin-managed."""
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise ValueError("User not found")
    user.voice_replies = voice_replies
    user.updated_at = datetime.now(timezone.utc)
    db.add(user)
    await db.commit()

    await _cache_delete(_profile_key(user_id))

    await _emit(
        "voice_replies.updated",
        user_id,
        email=user.email,
        metadata={"voice_replies": voice_replies},
    )

    return await get_profile(user_id, db)


async def update_typing_indicator(user_id: str, enabled: bool, db: AsyncSession) -> dict:
    """Persist the tenant's typing-indicator preference (same write path as
    voice replies). The consumer reads this per incoming message, so it takes
    effect for the next reply without a restart."""
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise ValueError("User not found")
    user.typing_indicator = enabled
    user.updated_at = datetime.now(timezone.utc)
    db.add(user)
    await db.commit()

    await _cache_delete(_profile_key(user_id))

    await _emit(
        "typing_indicator.updated",
        user_id,
        email=user.email,
        metadata={"typing_indicator": enabled},
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


async def list_feedback(user_id: str, db: AsyncSession) -> list[dict]:
    rows = (
        await db.execute(select(UserFeedback).where(UserFeedback.user_id == user_id))
    ).scalars().all()
    return [{"emoji_rating": r.emoji_rating, "message": r.message, "created_at": r.created_at.isoformat() if r.created_at else None} for r in rows]


async def submit_feedback(user_id: str, emoji_rating: int, message: str | None, db: AsyncSession) -> list[dict]:
    if emoji_rating < 1 or emoji_rating > 5:
        raise ValueError("emoji_rating must be between 1 and 5")

    row = UserFeedback(user_id=user_id, emoji_rating=emoji_rating, message=message)
    db.add(row)
    await db.commit()

    await _cache_delete(_profile_key(user_id), _usage_key(user_id))

    await _emit(
        "feedback.submitted",
        user_id,
        metadata={"emoji_rating": emoji_rating},
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
    # The LLM-distilled business card (databank uploads) joins the same
    # context so every format_business_identity consumer gets it for free.
    # Separate savepoint: a missing business_profiles table (pre-migration
    # DB) must not wipe the user facts probed above.
    try:
        from .business_profile import PROFILE_FIELDS
        from .models import BusinessProfile

        async with db.begin_nested():
            row = (
                await db.execute(
                    select(BusinessProfile).where(BusinessProfile.user_id == user_id)
                )
            ).scalar_one_or_none()
        if row is not None:
            for field in PROFILE_FIELDS:
                value = (getattr(row, field, None) or "").strip()
                if value:
                    ctx[f"business_{field}"] = value
    except Exception:
        pass
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
    # Business card fields (LLM-distilled from the databank, editable) —
    # rendered last so owner-configured facts above always lead the block.
    if ctx.get("business_summary"):
        lines.append(f"- Summary: {ctx['business_summary'][:700]}")
    if ctx.get("business_domain"):
        lines.append(f"- Domain: {ctx['business_domain'][:200]}")
    if ctx.get("business_products_services"):
        lines.append(f"- Offers: {ctx['business_products_services'][:800]}")
    if ctx.get("business_not_offered_and_policies"):
        lines.append(
            "- Does NOT offer / policies: "
            f"{ctx['business_not_offered_and_policies'][:500]}"
        )
    if ctx.get("business_audience_languages"):
        lines.append(
            f"- Audience & languages: {ctx['business_audience_languages'][:300]}"
        )
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

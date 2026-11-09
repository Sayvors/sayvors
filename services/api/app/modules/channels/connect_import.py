"""Durable first-connect Google import + AI draft generation.

The normal review poll is deliberately slow (5 minutes) and the live worker
must not be blocked by a 300-review historical backfill. This module owns a
separate, bounded pipeline:

  fetch all reviews -> wait for the merchant's scope -> generate drafts ->
  publish only what the merchant selected.

Every state transition is persisted in `connect_import_sessions` /
`connect_import_items`, so closing the modal, navigating away or reloading the
page resumes the same session. Drafts live in `review_replies` with
`pending_approval`, which also keeps them in Outbox if the modal is dismissed.
"""
from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..analytics.models import ReviewInsight
from ..billing.budget import BudgetExhausted
from .google_reviews import GoogleReviewsClient, GoogleReviewsError
from .models import (
    AutoReplyConfig,
    Channel,
    ConnectImportEvent,
    ConnectImportItem,
    ConnectImportSession,
    ReviewReply,
)
from .review_reply import generate_auto_reply
from .service import decrypt_token

logger = logging.getLogger(__name__)

# Bounded concurrency. Per-session keeps one tenant from monopolising the
# provider; the global limit protects the provider and leaves room for live
# auto-replies. Both are intentionally small enough to avoid 429 bursts.
GENERATE_PER_SESSION = 3
GENERATE_GLOBAL = 8
FETCH_PER_SESSION = 3
PUBLISH_PER_SESSION = 3
WORKER_SESSIONS = 3
WORKER_POLL_SECONDS = 5
SESSION_LEASE_SECONDS = 3600
MAX_ITEMS = 5000

SCOPE_CHOICES = (30, 180, 365, 0)  # 0 = all time
DEFAULT_SCOPE_DAYS = 180

_GENERATE_GLOBAL_SEMAPHORE = asyncio.Semaphore(GENERATE_GLOBAL)


def _meta(channel: Channel) -> dict:
    try:
        value = json.loads(channel.metadata_json or "{}")
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _listing_id(channel: Channel) -> str:
    return str(
        _meta(channel).get("location_id")
        or channel.platform_user_id
        or channel.listing_key
        or channel.id
    )


def _cutoff(scope_days: int, now: datetime | None = None) -> datetime | None:
    if not scope_days:
        return None
    return (now or datetime.now(timezone.utc)) - timedelta(days=scope_days)


async def create_session(db: AsyncSession, user_id: str) -> ConnectImportSession:
    """Create or resume the durable import session the callback redirects to.

    Reconnecting while an import is still active must not create a second
    session: both workers would draft the same reviews. Reset the existing
    session to ``queued`` so the fetch pass picks up any newly connected
    locations and keeps already-generated drafts.
    """
    existing = await latest_active_session(db, user_id)
    if existing is not None:
        if existing.status in ("generating", "publishing"):
            return existing
        existing.status = "queued"
        existing.locked_until = None
        existing.error = None
        await _log(db, existing.id, "Google is reconnected. Picking up where we left off.")
        await db.commit()
        await db.refresh(existing)
        return existing

    session = ConnectImportSession(
        user_id=user_id,
        status="queued",
        scope_days=DEFAULT_SCOPE_DAYS,
    )
    db.add(session)
    await db.flush()
    await _log(db, session.id, "Google is connected. We're getting your reviews ready.")
    await db.commit()
    await db.refresh(session)
    return session


async def _log(
    db: AsyncSession, session_id: str, message: str, level: str = "info"
) -> None:
    """Queue one progress-feed row. The caller's next commit persists it."""
    db.add(
        ConnectImportEvent(
            session_id=session_id,
            level=level,
            message=message[:1000],
        )
    )


def _plural(count: int, singular: str, plural: str | None = None) -> str:
    """Readable counts for merchant-facing copy ("1 review", "3 reviews")."""
    return f"{count} {singular if count == 1 else (plural or singular + 's')}"


async def session_events(
    db: AsyncSession, session_id: str, limit: int = 120
) -> list[ConnectImportEvent]:
    rows = (
        await db.execute(
            select(ConnectImportEvent)
            .where(ConnectImportEvent.session_id == session_id)
            .order_by(ConnectImportEvent.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    return list(reversed(rows))


async def get_session(
    db: AsyncSession, user_id: str, session_id: str
) -> ConnectImportSession | None:
    result = await db.execute(
        select(ConnectImportSession).where(
            ConnectImportSession.id == session_id,
            ConnectImportSession.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


async def latest_active_session(
    db: AsyncSession, user_id: str
) -> ConnectImportSession | None:
    result = await db.execute(
        select(ConnectImportSession)
        .where(
            ConnectImportSession.user_id == user_id,
            ConnectImportSession.status.notin_(("completed", "failed")),
        )
        .order_by(ConnectImportSession.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def session_items(
    db: AsyncSession, session_id: str
) -> list[ConnectImportItem]:
    result = await db.execute(
        select(ConnectImportItem)
        .where(ConnectImportItem.session_id == session_id)
        .order_by(ConnectImportItem.review_time.desc().nullslast())
        .limit(MAX_ITEMS)
    )
    return list(result.scalars().all())


async def start_generation(
    db: AsyncSession, session: ConnectImportSession, scope_days: int
) -> ConnectImportSession:
    """Apply the merchant's scope choice and queue draft generation."""
    if scope_days not in SCOPE_CHOICES:
        raise ValueError("scope_days must be one of 30, 180, 365 or 0")
    if session.status != "awaiting_scope":
        raise ValueError("This import is not waiting for a scope choice")

    session.scope_days = scope_days
    cutoff = _cutoff(scope_days)
    items = await session_items(db, session.id)
    for item in items:
        if item.status != "pending":
            continue
        if cutoff is not None and item.review_time is not None and item.review_time < cutoff:
            item.status = "outside_scope"
    session.total_drafts = sum(1 for item in items if item.status == "pending")
    session.drafts_ready = 0
    session.drafts_failed = 0
    session.status = "generating"
    label = "your full history" if not scope_days else (
        "the last 30 days" if scope_days == 30 else
        "the last 6 months" if scope_days == 180 else
        "the last 12 months"
    )
    await _log(
        db, session.id,
        f"Writing AI replies for {_plural(session.total_drafts, 'review')} from {label}.",
    )
    session.locked_until = None
    await db.commit()
    await db.refresh(session)
    return session


async def request_item_generation(
    db: AsyncSession, session: ConnectImportSession, item_id: str
) -> ConnectImportSession:
    """Generate one draft outside the selected scope (or retry one failure)."""
    if session.status != "ready":
        raise ValueError("Finish the current import before generating another draft")
    item = await db.get(ConnectImportItem, item_id)
    if item is None or item.session_id != session.id:
        raise ValueError("Review not found in this import")
    if item.status not in ("outside_scope", "failed"):
        raise ValueError("This review is not eligible for a manual draft")
    item.status = "pending"
    item.error = None
    session.total_drafts = (session.total_drafts or 0) + 1
    session.status = "generating"
    session.locked_until = None
    await db.commit()
    await db.refresh(session)
    return session


async def request_publish(
    db: AsyncSession,
    session: ConnectImportSession,
    *,
    item_ids: list[str] | None = None,
    publish_all: bool = False,
) -> ConnectImportSession:
    """Mark drafts for the worker to publish. Never publishes inline."""
    if session.status != "ready":
        raise ValueError("This import is not ready to publish")
    filters = [
        ConnectImportItem.session_id == session.id,
        ConnectImportItem.status == "draft_ready",
    ]
    if not publish_all:
        ids = [str(value) for value in (item_ids or []) if value]
        if not ids:
            raise ValueError("Select at least one review or publish all drafts")
        filters.append(ConnectImportItem.id.in_(ids))
    await db.execute(
        update(ConnectImportItem)
        .where(*filters)
        .values(selected=True)
    )
    selected = (
        await db.execute(
            select(ConnectImportItem.id)
            .where(
                ConnectImportItem.session_id == session.id,
                ConnectImportItem.selected.is_(True),
                ConnectImportItem.status == "draft_ready",
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    if selected is None:
        raise ValueError("No generated drafts match the selection")
    session.status = "publishing"
    session.locked_until = None
    await _log(
        db,
        session.id,
        "Posting your replies to Google.",
    )
    await db.commit()
    await db.refresh(session)
    return session


async def record_publish_failure(
    db: AsyncSession, item: ConnectImportItem, error: str
) -> None:
    item.status = "publish_failed"
    item.error = error[:2000]
    if item.reply_id:
        reply = await db.get(ReviewReply, item.reply_id)
        if reply is not None:
            reply.status = "failed"
            reply.error = error[:2000]
    await db.commit()


async def _claim_session(db: AsyncSession) -> ConnectImportSession | None:
    """Claim one runnable session with a crash-safe lease."""
    now = datetime.now(timezone.utc)
    stmt = (
        select(ConnectImportSession)
        .where(
            ConnectImportSession.status.in_(("queued", "fetching", "generating", "publishing")),
            (ConnectImportSession.locked_until.is_(None))
            | (ConnectImportSession.locked_until < now),
        )
        .order_by(ConnectImportSession.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    session = (await db.execute(stmt)).scalar_one_or_none()
    if session is None:
        return None
    lease = 600 if session.status in ("queued", "fetching") else SESSION_LEASE_SECONDS
    session.locked_until = now + timedelta(seconds=lease)
    await db.commit()
    await db.refresh(session)
    return session


async def _fetch_channel_reviews(
    channel: Channel,
) -> tuple[Channel, list, str | None]:
    access_token = decrypt_token(channel.access_token) if channel.access_token else None
    refresh_token = decrypt_token(channel.refresh_token) if channel.refresh_token else None
    if not access_token and not refresh_token:
        return channel, [], "Google credentials are missing"
    client = GoogleReviewsClient(access_token or "", refresh_token)
    client.set_known_expiry(channel.token_expires_at)
    try:
        reviews = await client.list_reviews(
            channel.platform_user_id, _listing_id(channel)
        )
        return channel, reviews, None
    except GoogleReviewsError as e:
        return channel, [], str(e)[:500]
    finally:
        await client.close()


async def _ensure_insight(
    db: AsyncSession, channel: Channel, review
) -> None:
    """Make the review visible on the reviews page immediately.

    The normal analytics consumer owns enrichment, but waiting for the next
    poll to create the row would leave the modal's freshly imported review
    invisible outside the modal.
    """
    from .reviews_worker import _store_inbound_review

    # Also seed the inbox thread now. The import can finish before the next
    # 5-minute review poll; without this, the review exists in Analytics but
    # not in the conversation list.
    await _store_inbound_review(db, channel.id, review)

    existing = (
        await db.execute(
            select(ReviewInsight.id).where(
                ReviewInsight.channel_id == channel.id,
                ReviewInsight.review_id == review.review_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return
    db.add(
        ReviewInsight(
            user_id=channel.user_id,
            channel_id=channel.id,
            review_id=review.review_id,
            rating=review.rating,
            review_text=review.text,
            reviewer_name=review.reviewer_name,
            reviewer_photo_url=getattr(review, "reviewer_photo_url", None),
            sentiment="neutral",
            sentiment_score=0.0,
            topics=[],
            products=[],
            problems=[],
            enrichment_status="pending",
            review_updated_at=review.updated_at or datetime.now(timezone.utc),
            last_seen_at=datetime.now(timezone.utc),
        )
    )
    # Re-use the normal discovery event so sentiment/topics/products arrive
    # from the analytics consumer without duplicating its prompt logic here.
    try:
        from .reviews_worker import _enqueue_review_discovered

        await _enqueue_review_discovered(db, channel, review)
    except Exception as e:  # noqa: BLE001
        logger.warning("Import discovery event failed for %s: %s", review.review_id, e)


async def _adopt_google_reply(db: AsyncSession, channel: Channel, review):
    """Import the reply Google already shows and return its local row.

    The regular review poll already adopts live Google replies before deciding
    a review is answered. The first-connect import must use the same rule, or
    it drafts a second response over a reply the merchant can see on Google.
    """
    from .reviews_worker import _adopt_existing_reply

    await _adopt_existing_reply(db, channel, review)
    return (
        await db.execute(
            select(ReviewReply)
            .where(
                ReviewReply.channel_id == channel.id,
                ReviewReply.review_id == review.review_id,
            )
            .order_by(ReviewReply.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def _fetch_phase(db: AsyncSession, session: ConnectImportSession) -> None:
    session.status = "fetching"
    await _log(db, session.id, "Connecting to Google Business Profile.")
    await db.commit()

    channels = (
        await db.execute(
            select(Channel).where(
                Channel.user_id == session.user_id,
                Channel.platform == "google_reviews",
                Channel.status == "active",
                (Channel.access_token.isnot(None))
                | (Channel.refresh_token.isnot(None)),
            )
        )
    ).scalars().all()
    session.total_locations = len(channels)
    session.total_reviews = 0
    session.fetched_reviews = 0
    session.fetched_locations = 0
    await db.commit()

    semaphore = asyncio.Semaphore(FETCH_PER_SESSION)

    async def _one(channel: Channel):
        async with semaphore:
            return await _fetch_channel_reviews(channel)

    results = await asyncio.gather(*[_one(c) for c in channels], return_exceptions=True)
    errors: list[str] = []
    for result in results:
        if isinstance(result, Exception):
            errors.append(str(result)[:200])
            await _log(
                db,
                session.id,
                "We couldn't load one of your Google locations right now. We'll try again later.",
                "warning",
            )
            continue
        channel, reviews, error = result
        if error:
            errors.append(f"{channel.display_name or channel.id}: {error}")
            await _log(
                db, session.id,
                f"We couldn't load {channel.display_name or 'this location'} right now. We'll try again later.",
                "warning",
            )
            continue
        existing_items = {
            (item.channel_id, item.review_id): item
            for item in (
                await db.execute(
                    select(ConnectImportItem).where(
                        ConnectImportItem.session_id == session.id,
                        ConnectImportItem.channel_id == channel.id,
                    )
                )
            ).scalars().all()
        }
        existing_replies = {
            reply.review_id: reply
            for reply in (
                await db.execute(
                    select(ReviewReply).where(ReviewReply.channel_id == channel.id)
                )
            ).scalars().all()
        }
        for review in reviews:
            session.total_reviews = (session.total_reviews or 0) + 1
            already_on_google = bool(getattr(review, "has_reply", False))
            if (channel.id, review.review_id) in existing_items:
                existing = existing_items[(channel.id, review.review_id)]
                if already_on_google:
                    # A resumed import may have left this row failed before the
                    # budget gate was fixed, or before the Google reply was
                    # adopted. Google wins: correct the row in place.
                    reply = await _adopt_google_reply(db, channel, review)
                    existing.status = "already_replied"
                    existing.reply_id = reply.id if reply is not None else None
                    existing.error = None
                elif existing.status == "generating":
                    existing.status = "pending"
                    existing.error = None
                session.fetched_reviews = (session.fetched_reviews or 0) + 1
                continue
            reply = existing_replies.get(review.review_id)
            if already_on_google:
                reply = await _adopt_google_reply(db, channel, review)
                existing_replies[review.review_id] = reply
            already = already_on_google or (
                reply is not None
                and reply.status in ("pending_approval", "posted", "approved")
            )
            item = ConnectImportItem(
                session_id=session.id,
                channel_id=channel.id,
                review_id=review.review_id,
                location_name=channel.display_name,
                reviewer_name=review.reviewer_name,
                rating=review.rating,
                review_text=review.text,
                review_time=review.updated_at or datetime.now(timezone.utc),
                status="already_replied" if already else "pending",
                reply_id=reply.id if already and reply is not None else None,
            )
            db.add(item)
            await _ensure_insight(db, channel, review)
            session.fetched_reviews = (session.fetched_reviews or 0) + 1
        session.fetched_locations = (session.fetched_locations or 0) + 1
        await _log(
            db, session.id,
            f"Found {_plural(len(reviews), 'review')} at {channel.display_name or 'this location'}.",
            "success",
        )
        await db.commit()

    session.total_drafts = sum(
        1 for item in await session_items(db, session.id) if item.status == "pending"
    )
    session.error = "; ".join(errors)[:4000] or None
    if session.total_reviews == 0:
        session.status = "completed"
        session.locked_until = None
        await _write_summary(db, session)
        await _log(db, session.id, "We didn't find any reviews on your Google locations yet.", "warning")
    else:
        session.status = "awaiting_scope"
        await _log(
            db, session.id,
            f"Found {_plural(session.fetched_reviews, 'review')} across {_plural(session.fetched_locations, 'location')}.",
            "success",
        )
    await db.commit()


async def _generate_one(session_id: str, item_id: str, semaphore: asyncio.Semaphore) -> None:
    from ...database import async_session

    async with semaphore:
        async with _GENERATE_GLOBAL_SEMAPHORE:
            async with async_session() as db:
                item = await db.get(ConnectImportItem, item_id)
                if item is None or item.status != "pending":
                    return
                session = await db.get(ConnectImportSession, session_id)
                channel = await db.get(Channel, item.channel_id)
                if session is None or channel is None:
                    return
                item.status = "generating"
                await db.commit()

                config = (
                    await db.execute(
                        select(AutoReplyConfig).where(
                            AutoReplyConfig.channel_id == channel.id
                        )
                    )
                ).scalar_one_or_none()
                if config is None:
                    config = AutoReplyConfig(channel_id=channel.id)
                    db.add(config)
                    await db.flush()

                try:
                    text, _ = await generate_auto_reply(
                        config,
                        channel,
                        item.rating,
                        item.review_text,
                        item.reviewer_name,
                        db,
                        review_id=item.review_id,
                    )
                    # One draft per review, ever. A retry after an interrupted
                    # generation used to stack a fresh pending row on top of the
                    # one the first pass already wrote — the merchant saw more
                    # drafts than reviews (7 drafts from 5 reviews) and the
                    # approval queue filled with duplicates of one review.
                    posted = (
                        await db.execute(
                            select(ReviewReply)
                            .where(
                                ReviewReply.channel_id == channel.id,
                                ReviewReply.review_id == item.review_id,
                                ReviewReply.status == "posted",
                            )
                            .limit(1)
                        )
                    ).scalar_one_or_none()
                    if posted is not None:
                        # The review was answered between passes; a draft would
                        # double-reply on publish.
                        item.reply_id = posted.id
                        item.status = "already_replied"
                        item.error = None
                        await _log(
                            db, session.id,
                            f"{item.reviewer_name or 'A reviewer'} was already answered on Google.",
                            "success",
                        )
                        await db.commit()
                        return
                    existing = (
                        await db.execute(
                            select(ReviewReply)
                            .where(
                                ReviewReply.channel_id == channel.id,
                                ReviewReply.review_id == item.review_id,
                                ReviewReply.status == "pending_approval",
                            )
                            .order_by(ReviewReply.created_at.asc())
                            .limit(1)
                        )
                    ).scalar_one_or_none()
                    if existing is not None:
                        # Reuse: refresh the text in place and keep a single
                        # pending row per review.
                        existing.reply_text = text
                        existing.error = None
                        reply = existing
                    else:
                        reply = ReviewReply(
                            channel_id=channel.id,
                            review_id=item.review_id,
                            rating=item.rating,
                            review_text=item.review_text,
                            reviewer_name=item.reviewer_name,
                            reply_text=text,
                            status="pending_approval",
                            generation_attempt=1,
                        )
                        db.add(reply)
                        # A stale failed row for the same review would sit in
                        # the failed tab next to the fresh draft — retire it
                        # (the approve flow collapses siblings the same way).
                        await db.execute(
                            update(ReviewReply)
                            .where(
                                ReviewReply.channel_id == channel.id,
                                ReviewReply.review_id == item.review_id,
                                ReviewReply.status == "failed",
                            )
                            .values(status="rejected", error="Replaced by a new draft")
                        )
                    await db.flush()
                    item.reply_id = reply.id
                    item.status = "draft_ready"
                    item.error = None
                    await _log(
                        db, session.id,
                        f"Reply ready for {item.reviewer_name or 'a reviewer'}.",
                        "success",
                    )
                    await db.execute(
                        update(ConnectImportSession)
                        .where(ConnectImportSession.id == session.id)
                        .values(drafts_ready=ConnectImportSession.drafts_ready + 1)
                    )
                    await db.commit()
                    try:
                        from ..outbox.service import enqueue_event_in

                        await enqueue_event_in(
                            db,
                            "review.replied",
                            {
                                "user_id": channel.user_id,
                                "channel_id": channel.id,
                                "review_id": item.review_id,
                                "status": "pending_approval",
                            },
                            topic="review-events",
                        )
                        await db.commit()
                    except Exception as e:  # noqa: BLE001
                        logger.warning("Import reply event failed for %s: %s", item.review_id, e)
                except Exception as e:  # noqa: BLE001
                    await db.rollback()
                    item = await db.get(ConnectImportItem, item_id)
                    if item is None:
                        return
                    item.status = "failed"
                    item.error = (
                        "AI credits are used up. Add credit to keep writing replies."
                        if isinstance(e, BudgetExhausted)
                        else str(e)[:2000]
                    )
                    await _log(
                        db, session_id,
                        (
                            f"AI credits are used up, so we couldn't write a reply for {item.reviewer_name or 'a reviewer'}."
                            if isinstance(e, BudgetExhausted)
                            else f"We couldn't write a reply for {item.reviewer_name or 'a reviewer'} yet. You can try again from the list."
                        ),
                        "warning",
                    )
                    await db.execute(
                        update(ConnectImportSession)
                        .where(ConnectImportSession.id == session_id)
                        .values(drafts_failed=ConnectImportSession.drafts_failed + 1)
                    )
                    await db.commit()
                    logger.warning("Import draft failed for %s: %s", item.review_id, e)


async def _generate_phase(db: AsyncSession, session: ConnectImportSession) -> None:
    # We hold this session's lease, so nobody else can be generating its
    # items. Any row still marked "generating" was abandoned by a previous
    # process (crash, deploy, cancelled shutdown) — reset it so this pass
    # retries the draft instead of stranding it as a permanent failure.
    # Previously only rows older than STALE_ITEM_SECONDS were reset, which
    # left freshly interrupted work stuck: the stale check did not fire, no
    # "pending" rows were found, and the session was marked complete while
    # the drafts had never been written.
    await db.execute(
        update(ConnectImportItem)
        .where(
            ConnectImportItem.session_id == session.id,
            ConnectImportItem.status == "generating",
        )
        .values(status="pending", error=None)
    )
    await db.commit()
    items = (
        await db.execute(
            select(ConnectImportItem.id).where(
                ConnectImportItem.session_id == session.id,
                ConnectImportItem.status == "pending",
            )
        )
    ).scalars().all()
    if not items:
        session.status = "completed"
        session.locked_until = None
        await _write_summary(db, session)
        await _log(db, session.id, "Every review in this range already has a reply.", "success")
        await db.commit()
        return

    semaphore = asyncio.Semaphore(GENERATE_PER_SESSION)
    results = await asyncio.gather(
        *[_generate_one(session.id, item_id, semaphore) for item_id in items],
        return_exceptions=True,
    )
    # A cancelled task (worker shutdown mid-draft) is not a model failure.
    # Leave those rows "generating" and re-raise: the session stays claimable,
    # and the next process resets them to "pending" at the top of this phase.
    # Condemning them here turned every deploy into permanent "Generation
    # interrupted" rows the merchant had to retry by hand.
    if any(isinstance(r, asyncio.CancelledError) for r in results):
        raise asyncio.CancelledError()
    # A task that died before its own failure handler must not leave a row
    # stuck in "generating" forever.
    await db.execute(
        update(ConnectImportItem)
        .where(
            ConnectImportItem.session_id == session.id,
            ConnectImportItem.status == "generating",
        )
        .values(status="failed", error="Generation interrupted")
    )
    await db.refresh(session)
    session.status = "ready"
    session.locked_until = None
    done_rows = (
        await db.execute(
            select(ConnectImportItem.location_name, func.count(ConnectImportItem.id))
            .where(
                ConnectImportItem.session_id == session.id,
                ConnectImportItem.status == "draft_ready",
            )
            .group_by(ConnectImportItem.location_name)
        )
    ).all()
    for location_name, count in done_rows:
        await _log(
            db,
            session.id,
            f"{_plural(count, 'reply', 'replies')} are ready for {location_name or 'this location'}.",
            "success",
        )
    await _write_summary(db, session)
    await _log(
        db, session.id,
        (
            f"{_plural(session.drafts_ready, 'reply', 'replies')} are ready. {_plural(session.drafts_failed, 'reply', 'replies')} {'needs' if session.drafts_failed == 1 else 'need'} another try."
            if session.drafts_failed
            else f"{_plural(session.drafts_ready, 'reply', 'replies')} are ready."
        ),
        "success" if not session.drafts_failed else "warning",
    )
    await db.commit()


async def _publish_one(session_id: str, item_id: str, semaphore: asyncio.Semaphore) -> None:
    from ...database import async_session

    async with semaphore:
        async with async_session() as db:
            item = await db.get(ConnectImportItem, item_id)
            if item is None or item.status != "draft_ready" or not item.selected:
                return
            channel = await db.get(Channel, item.channel_id)
            reply = await db.get(ReviewReply, item.reply_id) if item.reply_id else None
            if channel is None or reply is None:
                item.status = "publish_failed"
                item.error = "Draft or channel no longer exists"
                await db.commit()
                return
            access_token = decrypt_token(channel.access_token) if channel.access_token else None
            refresh_token = decrypt_token(channel.refresh_token) if channel.refresh_token else None
            client = GoogleReviewsClient(access_token or "", refresh_token)
            client.set_known_expiry(channel.token_expires_at)
            try:
                if not access_token:
                    await client.refresh_access_token()
                await client.reply_to_review(reply.review_id, reply.reply_text)
                if not await client.confirm_reply_live(reply.review_id):
                    raise GoogleReviewsError("Reply did not appear on Google", 502)
                reply.status = "posted"
                reply.error = None
                item.status = "published"
                item.error = None
                from .reviews_worker import _store_reply_message

                await _store_reply_message(
                    db,
                    channel,
                    item.review_id,
                    item.reviewer_name,
                    reply,
                    status="sent",
                    handled_by="ai",
                )
                await _log(
                    db,
                    session_id,
                    f"Your reply to {item.reviewer_name or 'a reviewer'} is live on Google.",
                    "success",
                )
                await db.commit()
                try:
                    from ..outbox.service import enqueue_event_in

                    await enqueue_event_in(
                        db,
                        "review.replied",
                        {
                            "user_id": channel.user_id,
                            "channel_id": channel.id,
                            "review_id": reply.review_id,
                            "status": "posted",
                        },
                        topic="review-events",
                    )
                    await db.commit()
                except Exception as e:  # noqa: BLE001
                    logger.warning("Import publish event failed for %s: %s", reply.review_id, e)
            except Exception as e:  # noqa: BLE001
                await db.rollback()
                item = await db.get(ConnectImportItem, item_id)
                if item is None:
                    return
                item.status = "publish_failed"
                item.error = str(e)[:2000]
                reply = await db.get(ReviewReply, item.reply_id) if item.reply_id else None
                if reply is not None:
                    reply.status = "failed"
                    reply.error = str(e)[:2000]
                await _log(
                    db,
                    session_id,
                    f"We couldn't post your reply to {item.reviewer_name or 'a reviewer'}. You can try again.",
                    "warning",
                )
                await db.commit()
                logger.warning("Import publish failed for %s: %s", item.review_id, e)
            finally:
                await client.close()


async def _publish_phase(db: AsyncSession, session: ConnectImportSession) -> None:
    items = (
        await db.execute(
            select(ConnectImportItem.id).where(
                ConnectImportItem.session_id == session.id,
                ConnectImportItem.selected.is_(True),
                ConnectImportItem.status == "draft_ready",
            )
        )
    ).scalars().all()
    semaphore = asyncio.Semaphore(PUBLISH_PER_SESSION)
    await asyncio.gather(
        *[_publish_one(session.id, item_id, semaphore) for item_id in items],
        return_exceptions=True,
    )
    await db.execute(
        update(ConnectImportItem)
        .where(
            ConnectImportItem.session_id == session.id,
            ConnectImportItem.status == "draft_ready",
            ConnectImportItem.selected.is_(True),
        )
        .values(status="publish_failed", error="Publish interrupted")
    )
    await db.refresh(session)
    session.status = "completed"
    session.locked_until = None
    await _write_summary(db, session)
    summary = session.summary or {}
    failed = int(summary.get("failed") or 0)
    published = int(summary.get("published_now") or 0)
    await _log(
        db,
        session.id,
        (
            f"All done. {_plural(published, 'reply', 'replies')} posted, {failed} {'needs' if failed == 1 else 'need'} attention."
            if failed
            else f"All done. {_plural(published, 'reply', 'replies')} posted."
        ),
        "success" if not failed else "warning",
    )
    await db.commit()


async def _write_summary(db: AsyncSession, session: ConnectImportSession) -> None:
    items = await session_items(db, session.id)
    counts: dict[str, int] = defaultdict(int)
    for item in items:
        counts[item.status] += 1
    already = counts.get("already_replied", 0)
    total = len(items)
    published = counts.get("published", 0)
    failed = counts.get("failed", 0) + counts.get("publish_failed", 0)
    channel_ids = sorted({item.channel_id for item in items})

    oldest = None
    if channel_ids:
        from ..locations.models import LocationProfile
        from ..locations.service import listing_id_of

        channels = (
            await db.execute(select(Channel).where(Channel.id.in_(channel_ids)))
        ).scalars().all()
        listing_ids = set()
        for channel in channels:
            listing_ids.add(str(channel.id))
            listing_ids.add(listing_id_of(channel))
        rows = (
            await db.execute(
                select(LocationProfile.opening_date).where(
                    LocationProfile.user_id == session.user_id,
                    LocationProfile.listing_id.in_(listing_ids),
                    LocationProfile.opening_date.isnot(None),
                )
            )
        ).scalars().all()
        oldest = min((row for row in rows if row is not None), default=None)

    volume: dict[str, int] = defaultdict(int)
    scatter: list[dict] = []
    if channel_ids:
        cutoff = datetime.now(timezone.utc) - timedelta(days=365)
        rows = (
            await db.execute(
                select(ReviewInsight.review_updated_at, ReviewInsight.created_at, ReviewInsight.rating)
                .where(
                    ReviewInsight.channel_id.in_(channel_ids),
                    ReviewInsight.review_updated_at.isnot(None),
                    ReviewInsight.review_updated_at >= cutoff,
                )
            )
        ).all()
        for review_updated, created, rating in rows:
            stamp = review_updated or created
            if stamp is not None:
                volume[stamp.strftime("%Y-%m")] += 1
        for item in items:
            if item.review_time is not None:
                scatter.append({
                    "date": item.review_time.date().isoformat(),
                    "rating": item.rating,
                })

    months_old = None
    if oldest is not None:
        today = datetime.now(timezone.utc).date()
        months_old = (today.year - oldest.year) * 12 + (today.month - oldest.month)

    session.summary = {
        "reviews_total": total,
        "unanswered_before": max(0, total - already),
        "published_now": published,
        "already_answered": already,
        "failed": failed,
        "business_age_months": months_old,
        "review_volume": [
            {"month": month, "count": volume[month]} for month in sorted(volume)
        ],
        "rating_scatter": scatter[:500],
        "analytics_url": "/dashboard/analytics",
    }


async def process_session(session_id: str) -> None:
    from ...database import async_session

    async with async_session() as db:
        session = await db.get(ConnectImportSession, session_id)
        if session is None:
            return
        try:
            if session.status in ("queued", "fetching"):
                await _fetch_phase(db, session)
            elif session.status == "generating":
                await _generate_phase(db, session)
            elif session.status == "publishing":
                await _publish_phase(db, session)
        except Exception as e:  # noqa: BLE001
            await db.rollback()
            session = await db.get(ConnectImportSession, session_id)
            if session is not None:
                session.error = str(e)[:4000]
                session.status = "failed"
                session.locked_until = None
                await db.commit()
            logger.error("Connect import %s failed: %s", session_id, e, exc_info=True)


async def run_connect_import_worker() -> None:
    """Background loop for first-connect imports.

    Separate from live review polling so a large historical backfill cannot
    delay a new review reply. At most WORKER_SESSIONS sessions run at once;
    each session's draft generation is further bounded by its own semaphore.
    """
    tasks: set[asyncio.Task] = set()
    while True:
        try:
            done = {task for task in tasks if task.done()}
            tasks -= done
            for task in done:
                task.result()
            while len(tasks) < WORKER_SESSIONS:
                from ...database import async_session

                async with async_session() as db:
                    claimed = await _claim_session(db)
                if claimed is None:
                    break
                tasks.add(asyncio.create_task(process_session(claimed.id)))
        except Exception as e:  # noqa: BLE001
            logger.error("Connect import worker pass failed: %s", e)
        await asyncio.sleep(WORKER_POLL_SECONDS)

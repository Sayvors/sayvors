"""Google Reviews polling worker.

Google sends no webhooks for reviews, so connected Google Business Profile
channels are polled periodically. New (un-replied) reviews on channels with
auto-reply enabled are turned into replies:

  - rating >= config.min_rating_auto  -> generated and POSTED automatically
  - rating <  config.min_rating_auto  -> generated and queued as
                                         `pending_approval` for the merchant

Mock policy: GOOGLE_REVIEWS_MOCK mode NEVER persists anything. Fabricated
sample reviews used to be written as inbound messages and pipeline events —
that path is removed. In mock mode polling a channel is a logged no-op.

Leasing: each poll claims its channel via an atomic UPDATE on
`polling_locked_until`, so multiple worker instances never double-process
the same channel. The lock expires on its own (crash-safe).
"""
import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from ..outbox.service import enqueue_event
from .google_reviews import GoogleReviewsClient, GoogleReviewsError
from .models import AutoReplyConfig, Channel, ChannelMessage, ReviewReply
from .review_reply import generate_auto_reply
from ..notifications.service import notify
from .service import decrypt_token

logger = logging.getLogger(__name__)

LOCK_SECONDS = 120

# Kafka topics (delivered via the transactional outbox, modules/outbox)
REVIEW_EVENTS_TOPIC = "review-events"


def _channel_meta(channel: Channel) -> dict:
    try:
        return json.loads(channel.metadata_json or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}


async def _claim_channel(db: AsyncSession, config_id: str, last_polled_at) -> bool:
    """Atomically claim a channel for polling (multi-instance safe)."""
    now = datetime.now(timezone.utc)
    stmt = (
        update(AutoReplyConfig)
        .where(
            AutoReplyConfig.id == config_id,
            (AutoReplyConfig.polling_locked_until.is_(None))
            | (AutoReplyConfig.polling_locked_until < now),
        )
        .values(polling_locked_until=now + timedelta(seconds=LOCK_SECONDS))
    )
    result = await db.execute(stmt)
    await db.commit()
    return (result.rowcount or 0) > 0


async def _release_channel(db: AsyncSession, config_id: str) -> None:
    await db.execute(
        update(AutoReplyConfig)
        .where(AutoReplyConfig.id == config_id)
        .values(polling_locked_until=None, last_polled_at=datetime.now(timezone.utc))
    )
    await db.commit()


async def _already_replied(db: AsyncSession, review_id: str) -> bool:
    """True if this review already has a queued or posted reply.

    Only `pending_approval`/`posted` rows count: `failed` rows are
    retried on later polls, `rejected` rows were withdrawn on purpose.
    """
    result = await db.execute(
        select(ReviewReply.id)
        .where(
            ReviewReply.review_id == review_id,
            ReviewReply.status.in_(["pending_approval", "posted", "approved"]),
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


async def _draft_dismissed(db: AsyncSession, channel_id: str, review_id: str) -> bool:
    """True if the merchant rejected the draft for this review.

    The analytics consumer owns ReviewInsight rows and may not have created
    this one yet — missing row means "not dismissed", never an error.
    """
    from ..analytics.models import ReviewInsight

    try:
        row = (
            await db.execute(
                select(ReviewInsight.draft_dismissed).where(
                    ReviewInsight.channel_id == channel_id,
                    ReviewInsight.review_id == review_id,
                )
            )
        ).scalar_one_or_none()
    except Exception:
        return False
    return bool(row)


async def _clear_dismissal(db: AsyncSession, channel_id: str, review_id: str) -> None:
    """New review content re-arms drafting after a dismissal."""
    from ..analytics.models import ReviewInsight

    try:
        async with db.begin_nested():
            row = (
                await db.execute(
                    select(ReviewInsight).where(
                        ReviewInsight.channel_id == channel_id,
                        ReviewInsight.review_id == review_id,
                    )
                )
            ).scalar_one_or_none()
            if row is not None and row.draft_dismissed:
                row.draft_dismissed = False
                db.add(row)
                await db.flush()
    except Exception:
        pass


async def _resume_failed_row(
    db: AsyncSession, channel_id: str, review_id: str
) -> ReviewReply | None:
    """Newest `failed` row for this review, or None.

    Resuming that row (instead of inserting a fresh draft) keeps one row
    per review cycle: the failed list self-cleans when the retry succeeds
    or the draft is re-queued. Older failed duplicates — left behind by
    earlier polls — are collapsed to `rejected` here too.
    """
    result = await db.execute(
        select(ReviewReply)
        .where(
            ReviewReply.channel_id == channel_id,
            ReviewReply.review_id == review_id,
            ReviewReply.status == "failed",
        )
        .order_by(ReviewReply.created_at.desc())
        .limit(1)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None
    siblings = await db.execute(
        select(ReviewReply).where(
            ReviewReply.channel_id == channel_id,
            ReviewReply.review_id == review_id,
            ReviewReply.status == "failed",
            ReviewReply.id != row.id,
        )
    )
    for sibling in siblings.scalars().all():
        sibling.status = "rejected"
        sibling.error = None
    return row


def _save_reply_row(
    db: AsyncSession,
    row: ReviewReply | None,
    channel_id: str,
    review_id: str,
    rating: int,
    review_text: str | None,
    reviewer_name: str | None,
    reply_text: str,
    status: str,
    error: str | None = None,
) -> None:
    """Write `status` onto the resumed failed row in place, or insert a new row."""
    if row is not None:
        row.reply_text = reply_text
        row.rating = rating
        row.review_text = review_text
        row.reviewer_name = reviewer_name
        row.status = status
        # A fresh draft was generated to get here — count it.
        row.generation_attempt = (row.generation_attempt or 1) + 1
        row.error = error
        return
    db.add(
        ReviewReply(
            channel_id=channel_id,
            review_id=review_id,
            rating=rating,
            review_text=review_text,
            reviewer_name=reviewer_name,
            reply_text=reply_text,
            status=status,
            error=error,
        )
    )


async def _store_inbound_review(db: AsyncSession, channel_id: str, review) -> None:
    """Mirror the inbound review as a ChannelMessage so the UI can show it."""
    import uuid

    existing = await db.execute(
        select(ChannelMessage.id)
        .where(
            ChannelMessage.channel_id == channel_id,
            ChannelMessage.platform_message_id == review.review_id[:200],
        )
        .limit(1)
    )
    if existing.scalar_one_or_none():
        return
    db.add(
        ChannelMessage(
            id=str(uuid.uuid4()),
            channel_id=channel_id,
            platform_message_id=review.review_id[:200],
            direction="inbound",
            content=review.text or f"({review.rating}/5 stars, no comment)",
            content_type="review",
            status="read",
        )
    )
    await db.commit()


async def _enqueue_review_discovered(db: AsyncSession, channel: Channel, review) -> None:
    """Emit review.discovered (outbox → Kafka) for the analytics pipeline.

    Idempotent: skips reviews already enriched by the analytics consumer —
    unless the content changed, which means the reviewer edited it and the
    consumer must re-enrich and flag the edit.
    """
    from ..analytics.models import ReviewInsight

    existing = (
        await db.execute(
            select(ReviewInsight).where(
                ReviewInsight.channel_id == channel.id,
                ReviewInsight.review_id == review.review_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        same_content = (
            existing.rating == review.rating
            and (existing.review_text or None) == (review.text or None)
        )
        if same_content and existing.enrichment_status == "done":
            return
    await enqueue_event(
        "review.discovered",
        {
            "user_id": channel.user_id,
            "channel_id": channel.id,
            "review_id": review.review_id,
            "rating": review.rating,
            "text": review.text,
            "reviewer_name": review.reviewer_name,
            "reviewer_photo_url": getattr(review, "reviewer_photo_url", None),
            "review_updated_at": review.updated_at.isoformat() if review.updated_at else None,
            # Reviewer-attached photos. The consumer downloads and stores the
            # bytes, because Google's thumbnail URLs expire within hours.
            "media": getattr(review, "media", None) or [],
        },
        topic=REVIEW_EVENTS_TOPIC,
    )


async def _enqueue_review_replied(channel: Channel, review, status: str) -> None:
    """Emit review.replied so analytics tracks response rate/time."""
    await enqueue_event(
        "review.replied",
        {
            "user_id": channel.user_id,
            "channel_id": channel.id,
            "review_id": review.review_id,
            "status": status,
            "replied_at": datetime.now(timezone.utc).isoformat(),
        },
        topic=REVIEW_EVENTS_TOPIC,
    )


async def _refresh_edited_review_reply(
    db: AsyncSession, channel: Channel, config: AutoReplyConfig, review
) -> None:
    """Bring a queued/live response back in step with an edited review.

    Google polls return reviews updated since the last pass. When the text
    or rating changed after a reply was queued or posted, the response on
    file answers content that no longer exists: a still-pending draft is
    regenerated in place, and a posted reply gets a follow-up draft queued
    behind it. An edit follow-up never auto-posts — it always waits for
    approval (the same rule as the Localith sync path).
    """
    latest = (
        await db.execute(
            select(ReviewReply)
            .where(
                ReviewReply.channel_id == channel.id,
                ReviewReply.review_id == review.review_id,
                ReviewReply.status.in_(["pending_approval", "posted", "approved"]),
            )
            .order_by(ReviewReply.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if latest is None:
        return
    # Missing stored text (legacy rows, stars-only replies) gives no
    # baseline to compare — leave those alone.
    content_matches = (
        latest.rating == review.rating
        and (
            not latest.review_text
            or (latest.review_text or None) == (review.text or None)
        )
    )
    if content_matches:
        return  # reply already reflects the current content
    # New content re-arms drafting after a past dismissal.
    await _clear_dismissal(db, channel.id, review.review_id)
    is_pending = latest.status == "pending_approval"
    failed_row = None
    if is_pending:
        attempt = (latest.generation_attempt or 1) + 1
        previous_draft = latest.reply_text
    else:
        # posted/approved: a fresh follow-up draft cycle (resume a failed row if present).
        failed_row = await _resume_failed_row(db, channel.id, review.review_id)
        attempt = (failed_row.generation_attempt or 1) + 1 if failed_row else 1
        previous_draft = failed_row.reply_text if failed_row else None
    try:
        reply_text = await generate_auto_reply(
            config, channel, review.rating, review.text, review.reviewer_name, db,
            review_id=review.review_id,
            attempt=attempt,
            previous_draft=previous_draft,
        )
    except Exception as e:
        # Keep whatever is on file; the next poll retries the refresh.
        logger.warning("Edit follow-up draft failed for %s: %s", review.review_id, e)
        return
    if is_pending:
        latest.reply_text = reply_text
        latest.rating = review.rating
        latest.review_text = review.text
        latest.reviewer_name = review.reviewer_name
        latest.generation_attempt = attempt
        latest.error = None
    else:
        _save_reply_row(
            db, failed_row, channel.id, review.review_id,
            review.rating, review.text, review.reviewer_name,
            reply_text, "pending_approval",
        )
    await db.commit()


async def process_channel(db: AsyncSession, channel: Channel, config: AutoReplyConfig) -> dict:
    """Poll one Google Reviews channel and auto-reply to new reviews."""
    stats = {"reviews": 0, "replied": 0, "queued": 0, "skipped": 0, "errors": 0}

    mock_mode = settings.GOOGLE_REVIEWS_MOCK
    if mock_mode:
        logger.info(
            "Reviews poll: mock mode — skipping persistence for channel %s",
            channel.id,
        )
        return stats
    client = None

    access_token = decrypt_token(channel.access_token) if channel.access_token else None
    refresh_token = decrypt_token(channel.refresh_token) if channel.refresh_token else None
    if not access_token and not refresh_token:
        logger.error("Channel %s has no tokens; skipping", channel.id)
        return stats

    client = GoogleReviewsClient(access_token or "", refresh_token)
    # Seed the client with stored expiry so it can refresh proactively
    # before the first API call (avoids the first request always hitting 401).
    client.set_known_expiry(channel.token_expires_at)
    # Register a persister so any refresh-driven token is encrypted + written
    # back to the DB row — subsequent worker passes won't re-refresh.
    from .service import encrypt_token as _encrypt_token

    async def _persist_token(new_access_token: str, new_expires_at) -> None:
        channel.access_token = _encrypt_token(new_access_token)
        channel.token_expires_at = new_expires_at
        db.add(channel)
        try:
            await db.commit()
        except Exception as e:
            logger.error("Failed to persist refreshed token for %s: %s", channel.id, e)
            await db.rollback()

    client.set_token_persister(_persist_token)

    try:
        account_id = channel.platform_user_id or ""
        # Location is stored in channel metadata: {"location_id": "..."}
        location_id = _channel_meta(channel).get("location_id", "")
        if not account_id or not location_id:
            # Fall back: list locations and use the first.
            locations = await client.list_locations(account_id) if account_id else []
            if not locations:
                logger.warning("Channel %s: no account/location configured", channel.id)
                return stats
            location_id = locations[0]["name"].split("/")[3]
        reviews = await client.list_reviews(
            account_id, location_id, updated_after=config.last_polled_at
        )

        for review in reviews:
            stats["reviews"] += 1
            await _store_inbound_review(db, channel.id, review)
            # Analytics events run before the replied-check so content
            # changes on already-answered reviews (reviewer edits) still
            # reach the consumer. The enqueue is content-gated, so
            # steady-state polls stay quiet.
            try:
                await _enqueue_review_discovered(db, channel, review)
            except Exception as e:
                # Analytics events must never break auto-reply
                logger.warning("review.discovered enqueue failed for %s: %s", review.review_id, e)
            if await _already_replied(db, review.review_id):
                # Idempotency: a draft is already queued (or posted) for
                # this review — polling it again must not create a duplicate.
                # But if the reviewer edited the review since we replied or
                # queued a draft, first bring that response up to date.
                await _refresh_edited_review_reply(db, channel, config, review)
                stats["skipped"] += 1
                continue
            if await _draft_dismissed(db, channel.id, review.review_id):
                # The merchant rejected the draft: don't auto-draft again.
                # A reviewer edit clears the marker; manual regenerate
                # bypasses it.
                stats["skipped"] += 1
                continue
            failed_row = await _resume_failed_row(db, channel.id, review.review_id)

            try:
                reply_text = await generate_auto_reply(
                    config, channel, review.rating, review.text, review.reviewer_name, db,
                    review_id=review.review_id,
                    attempt=(failed_row.generation_attempt or 1) + 1 if failed_row else 1,
                    previous_draft=failed_row.reply_text if failed_row else None,
                )
            except Exception as e:
                logger.error("Reply generation failed for %s: %s", review.review_id, e)
                if failed_row is not None:
                    failed_row.error = str(e)[:2000]
                else:
                    db.add(
                        ReviewReply(
                            channel_id=channel.id,
                            review_id=review.review_id,
                            rating=review.rating,
                            review_text=review.text,
                            reviewer_name=review.reviewer_name,
                            reply_text="",
                            status="failed",
                            error=str(e)[:2000],
                        )
                    )
                await db.commit()
                stats["errors"] += 1
                continue

            needs_approval = (
                getattr(config, "approval_mode", "auto") == "approval"
                or review.rating < config.min_rating_auto
            )
            if not needs_approval:
                try:
                    await client.reply_to_review(review.review_id, reply_text)
                    if not await client.confirm_reply_live(review.review_id):
                        raise GoogleReviewsError(
                            "Google accepted the reply but it is not showing on the listing"
                        )
                    stats["replied"] += 1
                except GoogleReviewsError as e:
                    stats["errors"] += 1
                    _save_reply_row(
                        db, failed_row, channel.id, review.review_id,
                        review.rating, review.text, review.reviewer_name,
                        reply_text, "failed", str(e)[:2000],
                    )
                    await notify(
                        db, channel.user_id, "reply_failed",
                        f"Auto-reply failed for ★{review.rating} review",
                        str(e)[:160],
                        data={"review_id": review.review_id, "channel_id": channel.id},
                        href="/dashboard/outbox",
                    )
                    await db.commit()
                    continue
                _save_reply_row(
                    db, failed_row, channel.id, review.review_id,
                    review.rating, review.text, review.reviewer_name,
                    reply_text, "posted",
                )
                await notify(
                    db, channel.user_id, "reply_posted",
                    f"Auto-replied to ★{review.rating} review from {review.reviewer_name or 'a customer'}",
                    (reply_text or "")[:160],
                    data={"review_id": review.review_id, "channel_id": channel.id},
                    href="/dashboard/reviews",
                )
                await db.commit()
                try:
                    await _enqueue_review_replied(channel, review, "posted")
                except Exception as e:
                    logger.warning("review.replied enqueue failed for %s: %s", review.review_id, e)
            else:
                # Low rating: never auto-post — queue for human approval.
                _save_reply_row(
                    db, failed_row, channel.id, review.review_id,
                    review.rating, review.text, review.reviewer_name,
                    reply_text, "pending_approval",
                )
                await db.commit()
                stats["queued"] += 1
                try:
                    await _enqueue_review_replied(channel, review, "pending_approval")
                except Exception as e:
                    logger.warning("review.replied enqueue failed for %s: %s", review.review_id, e)

        return stats
    finally:
        if client:
            await client.close()


async def poll_once() -> dict:
    """One polling pass over all due Google Reviews channels. Returns totals."""
    from ...database import async_session

    totals = {"channels": 0, "reviews": 0, "replied": 0, "queued": 0, "skipped": 0, "errors": 0}
    now = datetime.now(timezone.utc)
    due_before = now - timedelta(seconds=settings.GOOGLE_REVIEWS_POLL_INTERVAL_SECONDS)

    async with async_session() as db:
        rows = (
            await db.execute(
                select(Channel, AutoReplyConfig)
                .join(AutoReplyConfig, AutoReplyConfig.channel_id == Channel.id)
                .where(
                    Channel.platform == "google_reviews",
                    Channel.status == "active",
                    # No `enabled` filter: the engine always generates and
                    # queues. Auto Pilot alone decides auto-post vs approval.
                    (AutoReplyConfig.last_polled_at.is_(None))
                    | (AutoReplyConfig.last_polled_at < due_before),
                )
            )
        ).all()

        for channel, config in rows:
            if not await _claim_channel(db, config.id, config.last_polled_at):
                continue  # another instance has it
            totals["channels"] += 1
            try:
                stats = await process_channel(db, channel, config)
                for k in ("reviews", "replied", "queued", "skipped", "errors"):
                    totals[k] += stats[k]
            except Exception as e:
                logger.error("Poll failed for channel %s: %s", channel.id, e)
                totals["errors"] += 1
            finally:
                await _release_channel(db, config.id)

    return totals


async def run_google_reviews_worker() -> None:
    """Background loop started from app lifespan."""
    while True:
        try:
            totals = await poll_once()
            if totals["reviews"]:
                logger.info("Google reviews poll: %s", totals)
        except Exception as e:
            logger.error("Google reviews poll pass failed: %s", e)
        await asyncio.sleep(max(30, settings.GOOGLE_REVIEWS_POLL_INTERVAL_SECONDS))

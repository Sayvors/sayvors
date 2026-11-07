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
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ...config import settings
from ..outbox.service import enqueue_event
from .google_reviews import GoogleReviewsClient, GoogleReviewsError
from .models import AutoReplyConfig, Channel, ChannelMessage, ReviewReply
from ..analytics.models import GoogleQuestionAnswer
from .review_reply import generate_auto_reply
from ..notifications.service import notify
from .service import decrypt_token, encrypt_message_content

logger = logging.getLogger(__name__)

LOCK_SECONDS = 120

# Channel ids already reported as having no stored Google credentials, so the
# poll loop warns once instead of on every cycle. Process-local by design: a
# restart re-surfaces the state, which is what you want after a redeploy.
_no_token_warned: set[str] = set()

# Kafka topics (delivered via the transactional outbox, modules/outbox)
REVIEW_EVENTS_TOPIC = "review-events"


def _channel_meta(channel: Channel) -> dict:
    try:
        return json.loads(channel.metadata_json or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}


def _channel_health(channel: Channel) -> dict:
    """Read the per-channel health block from metadata_json.

    Tracks consecutive poll failures so a struggling channel (e.g. Google
    returning sustained 429s) gets backed off instead of hammered on every
    cycle. Stored under the ``health`` key of the channel's metadata JSON —
    no schema migration required.
    """
    return _channel_meta(channel).get("health", {})


def _is_in_health_backoff(channel: Channel, now: datetime) -> bool:
    """True when this channel's health backoff window hasn't elapsed yet."""
    health = _channel_health(channel)
    until = health.get("backoff_until")
    if not until:
        return False
    try:
        return datetime.fromisoformat(until) > now
    except (ValueError, TypeError):
        return False


def _qa_due(channel: Channel, now: datetime) -> bool:
    """True when this channel's Q&A has not been polled within the interval."""
    last = _channel_meta(channel).get("qa", {}).get("last_polled_at")
    if not last:
        return True
    try:
        stamp = datetime.fromisoformat(str(last))
    except (ValueError, TypeError):
        return True
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return now - stamp >= timedelta(seconds=settings.GOOGLE_QA_POLL_INTERVAL_SECONDS)


def _mark_qa_polled(channel: Channel, now: datetime) -> None:
    """Record the attempt time so Q&A is not fetched on every review cycle."""
    try:
        meta = json.loads(channel.metadata_json or "{}")
    except (json.JSONDecodeError, TypeError):
        meta = {}
    meta["qa"] = {"last_polled_at": now.isoformat()}
    channel.metadata_json = json.dumps(meta)


async def _update_channel_health(
    db: AsyncSession, channel: Channel, success: bool, error_code: str | None = None
) -> None:
    """Persist per-channel health after a poll attempt.

    Success resets the failure counter; failure increments it and schedules
    an exponential backoff (2^failures minutes, capped at 24h) so a channel
    Google is rate-limiting gets breathing room instead of being retried
    every poll cycle.
    """
    try:
        meta = json.loads(channel.metadata_json or "{}")
    except (json.JSONDecodeError, TypeError):
        meta = {}

    health = meta.get("health", {})
    ts = datetime.now(timezone.utc).isoformat()

    if success:
        health["consecutive_failures"] = 0
        health["last_success_at"] = ts
        health.pop("last_failure_code", None)
        health.pop("backoff_until", None)
    else:
        failures = int(health.get("consecutive_failures", 0)) + 1
        health["consecutive_failures"] = failures
        health["last_failure_at"] = ts
        if error_code:
            health["last_failure_code"] = error_code
        backoff_minutes = min(2 ** failures, 1440)  # cap at 24h
        health["backoff_until"] = (
            datetime.now(timezone.utc) + timedelta(minutes=backoff_minutes)
        ).isoformat()

    meta["health"] = health
    channel.metadata_json = json.dumps(meta)
    db.add(channel)


# Google failures that do not fix themselves: the token was revoked (401
# after a failed refresh), the location was removed (404), or the account
# lost access (403). A channel in one of these states stays broken until the
# merchant reconnects - it is not a transient error to retry.
PERMANENT_GOOGLE_STATUSES = (401, 403, 404)


async def _mark_channel_expired(db: AsyncSession, channel: Channel, reason: str) -> None:
    """Mark a channel expired (once) and tell the merchant to reconnect.

    A revoked token, a removed location or a lost account does not repair
    itself. Leaving the channel "active" means the worker keeps polling a
    dead connection every cycle and the merchant is told nothing at all - a
    silently dead channel, which is what this fixes.
    """
    if channel.status == "expired":
        return
    channel.status = "expired"
    db.add(channel)
    await notify(
        db,
        channel.user_id,
        "channel_expired",
        f"Your {channel.platform} connection expired",
        (reason or "Reconnect to keep receiving reviews.")[:160],
        data={"channel_id": channel.id, "platform": channel.platform},
        href="/dashboard/channels",
    )


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


async def _mark_reviews_seen(db: AsyncSession, channel: Channel, reviews) -> None:
    """Record that this poll returned these reviews.

    Removal detection only trusts `last_seen_at` written by a real provider
    fetch (never a replayed Kafka event). The incremental poll is a real
    fetch, so this is the writer that keeps the daily sweep's evidence warm.
    """
    from ..analytics.models import ReviewInsight

    ids = [r.review_id for r in reviews if r.review_id]
    if not ids:
        return
    now = datetime.now(timezone.utc)
    for start in range(0, len(ids), 200):
        chunk = ids[start:start + 200]
        rows = (
            await db.execute(
                select(ReviewInsight).where(
                    ReviewInsight.channel_id == channel.id,
                    ReviewInsight.review_id.in_(chunk),
                )
            )
        ).scalars().all()
        for row in rows:
            row.last_seen_at = now
            row.removed_at = None
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


async def _adopt_existing_reply(db: AsyncSession, channel: Channel, review) -> bool:
    """Import the merchant reply Google already shows for this review.

    Without this, `_already_replied` only knew about rows Sayvors wrote, so a
    review answered directly in the Business Profile looked unanswered and the
    AI could overwrite that reply. The Google reply is the source of truth:
    a pending/failed draft is superseded, the posted row is corrected if the
    owner edited the reply in GBP, and analytics receives the provider's
    publish time.

    Returns True when a row was created or changed.
    """
    if not getattr(review, "has_reply", False):
        return False

    text = (getattr(review, "reply_text", None) or "").strip()
    reply_updated_at = getattr(review, "reply_updated_at", None)
    external_id = (
        f"google:{reply_updated_at.isoformat()}" if reply_updated_at else None
    )
    rows = (
        await db.execute(
            select(ReviewReply)
            .where(
                ReviewReply.channel_id == channel.id,
                ReviewReply.review_id == review.review_id,
            )
            .order_by(ReviewReply.created_at.desc())
        )
    ).scalars().all()
    latest = rows[0] if rows else None

    if latest is not None and latest.status == "posted":
        same_id = external_id is None or latest.reply_external_id == external_id
        if same_id and (latest.reply_text or "").strip() == text:
            return False

    if latest is None:
        latest = ReviewReply(
            channel_id=channel.id,
            review_id=review.review_id,
            rating=review.rating,
            review_text=review.text,
            reviewer_name=review.reviewer_name,
            reply_text="",
            status="posted",
        )
        db.add(latest)
    else:
        # Google's live reply outranks an unsent/failed draft. The merchant
        # can still replace it deliberately, but the app must not silently
        # publish over a response that is already public.
        for sibling in rows[1:]:
            if sibling.status in ("pending_approval", "failed", "approved"):
                sibling.status = "rejected"
                sibling.error = None

    latest.rating = review.rating
    latest.review_text = review.text
    latest.reviewer_name = review.reviewer_name
    latest.reply_text = text
    latest.status = "posted"
    latest.error = None
    latest.reply_external_id = external_id
    latest.replied_at = reply_updated_at
    await _store_reply_message(
        db, channel, review.review_id, review.reviewer_name, latest,
        status="read", handled_by="human",
    )
    await db.commit()

    try:
        await _enqueue_review_replied(
            db, channel, review, "posted", replied_at=reply_updated_at
        )
    except Exception as e:
        logger.warning(
            "review.replied enqueue failed for adopted reply %s: %s",
            review.review_id, e,
        )
    return True


async def _ensure_location_metadata(
    db: AsyncSession, channel: Channel, client, location_id: str
) -> None:
    """Backfill Place ID, Maps URL, address, category, phone and website.

    Channels created before `metadata` (and the profile fields) were requested
    during OAuth have only the location id. The QR/review-request surfaces need
    the Place ID; the dashboard completeness checks need phone/website. Fetch
    once and persist; `profile_fields_checked` records that the answer is real,
    including "Google returned no phone".
    """
    meta = _channel_meta(channel)
    if meta.get("profile_fields_checked") and meta.get("place_metadata_checked"):
        return
    try:
        loc = await client.get_location(location_id)
    except Exception as e:
        logger.warning("location metadata backfill failed for %s: %s", channel.id, e)
        return
    from .google_reviews import (
        location_address,
        location_category,
        location_phone,
        location_website,
        location_description,
        location_hours,
        location_categories,
        location_attributes,
        location_service_area,
        location_service_types,
    )

    try:
        attributes = await client.get_attributes(location_id)
    except Exception as e:  # noqa: BLE001
        logger.debug("attributes backfill failed for %s: %s", channel.id, e)
        attributes = []

    loc_meta = loc.get("metadata") or {}
    meta["place_id"] = loc_meta.get("placeId")
    meta["maps_url"] = loc_meta.get("mapsUrl")
    meta["address"] = location_address(loc)
    meta["category"] = location_category(loc)
    meta["phone"] = location_phone(loc)
    meta["website"] = location_website(loc)
    meta["description"] = location_description(loc)
    meta["hours"] = location_hours(loc)
    meta["categories"] = location_categories(loc)
    meta["attributes"] = location_attributes(attributes)
    meta["service_area"] = location_service_area(loc)
    meta["services"] = location_service_types(loc)
    meta["profile_fields_checked"] = True
    # Separate marker: a location with no Place ID yet (new/unverified) must
    # not be re-fetched on every poll.
    meta["place_metadata_checked"] = True
    channel.metadata_json = json.dumps(meta)
    from .service import sync_google_services

    await sync_google_services(
        db, channel, meta["services"], meta.get("category")
    )
    await db.commit()


async def _backfill_existing_replies(
    db: AsyncSession, channel: Channel, client, account_id: str, location_id: str
) -> int:
    """One-time full read so replies written before this fix are imported.

    The regular poll only asks for reviews updated after the last poll, so
    reviews imported before reply adoption existed would never be revisited.
    This fetches the full feed once, adopts any live merchant replies, and
    re-emits `review.discovered` so the analytics rating/content is corrected.
    It never generates or publishes an AI reply.
    """
    reviews = await client.list_reviews(account_id, location_id)
    adopted = 0
    for review in reviews:
        try:
            await _store_inbound_review(db, channel.id, review)
        except Exception as e:
            logger.warning("reply backfill inbound store failed for %s: %s", review.review_id, e)
        try:
            if await _adopt_existing_reply(db, channel, review):
                adopted += 1
        except Exception as e:
            logger.warning("reply backfill adoption failed for %s: %s", review.review_id, e)
        try:
            await _enqueue_review_discovered(db, channel, review)
        except Exception as e:
            logger.warning("reply backfill review.discovered failed for %s: %s", review.review_id, e)

    meta = _channel_meta(channel)
    meta["reply_backfill_done"] = True
    channel.metadata_json = json.dumps(meta)
    await db.commit()
    return adopted


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
    from .service import categorize_message as _categorize
    from .service import encrypt_contact_phone, hash_contact_phone

    category, priority = _categorize(
        review.text or "", platform="google_reviews", rating=review.rating
    )
    # A Google reviewer has no phone number, so without an identity of
    # their own EVERY review on the channel collapses into the catch-all
    # "unknown" thread — one bucket, no reviewer names, nothing that can
    # be flagged or answered. Google gives us a profile URL and a display
    # name; either identifies the reviewer, so the thread key is derived
    # from whichever is available and namespaced so it can never collide
    # with a real phone number.
    reviewer_key = _google_reviewer_key(review)
    db.add(
        ChannelMessage(
            id=str(uuid.uuid4()),
            channel_id=channel_id,
            platform_message_id=review.review_id[:200],
            direction="inbound",
            content=encrypt_message_content(
                review.text or f"({review.rating}/5 stars, no comment)"
            ),
            content_type="review",
            status="read",
            contact_name=getattr(review, "reviewer_name", None) or None,
            contact_phone=encrypt_contact_phone(reviewer_key),
            contact_phone_hash=hash_contact_phone(reviewer_key),
            category=category,
            priority=priority,
        )
    )
    await db.commit()


async def _store_reply_message(
    db: AsyncSession,
    channel: Channel,
    review_id: str,
    reviewer_name: str | None,
    reply,
    *,
    status: str = "read",
    handled_by: str = "human",
) -> None:
    """Mirror a Google review reply as an outbound chat message.

    The inbox is message-based; without this row the customer's review appears
    in the chat but the merchant's public response is invisible. The inbound
    row owns the synthetic Google contact key, so the reply joins the same
    thread instead of creating a second one.
    """
    if not getattr(reply, "reply_text", None):
        return
    inbound = (
        await db.execute(
            select(ChannelMessage)
            .where(
                ChannelMessage.channel_id == channel.id,
                ChannelMessage.platform_message_id == review_id[:200],
            )
            .order_by(ChannelMessage.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if inbound is None:
        logger.debug("No inbound review message for %s; reply not mirrored", review_id)
        return

    platform_id = f"google-reply:{reply.id}"[:200]
    existing = (
        await db.execute(
            select(ChannelMessage)
            .where(
                ChannelMessage.channel_id == channel.id,
                ChannelMessage.platform_message_id == platform_id,
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    content = encrypt_message_content(reply.reply_text)
    name = inbound.contact_name or reviewer_name
    if existing is not None:
        existing.content = content
        existing.status = status
        existing.contact_name = name
        db.add(existing)
    else:
        import uuid

        db.add(
            ChannelMessage(
                id=str(uuid.uuid4()),
                channel_id=channel.id,
                platform_message_id=platform_id,
                direction="outbound",
                content=content,
                content_type="review_reply",
                status=status,
                contact_phone=inbound.contact_phone,
                contact_phone_hash=inbound.contact_phone_hash,
                contact_name=name,
                handled_by=handled_by,
                is_ai=handled_by == "ai",
            )
        )
    await db.flush()


def _google_reviewer_key(review) -> str:
    """A stable, namespaced identity for a Google reviewer.

    Google does not expose a stable user id for a reviewer, so the
    profile URL is the best identifier available, with the display name
    as a fallback and the review id as the last resort. Whichever is
    used, it is hashed rather than stored raw:

    - a profile URL is long and full of characters that would have to
      survive being a URL path segment, a query parameter, a JSON
      payload and an encrypted column;
    - a fixed-length digest cannot overflow the column;
    - the digest is one-way, so the reviewer's Google profile URL is not
      recoverable from what we store — the same posture the repo takes
      with contact phone numbers, which are HMAC'd into
      `contact_phone_hash`.

    The "google:" prefix keeps the key from ever colliding with a real
    phone number, which is what the inbox groups threads by.

    The attributes are read defensively: a review object that does not
    carry them must not cost the tenant the review itself.
    """
    import hashlib

    identity = (
        getattr(review, "author_profile_url", None)
        or getattr(review, "reviewer_photo_url", None)
        or getattr(review, "author_name", None)
        or getattr(review, "reviewer_name", None)
        or ""
    ).strip().lower()
    if not identity:
        # Nothing identifies this reviewer — fall back to the review id so
        # the message still lands in a thread of its own.
        identity = str(review.review_id)
    return f"google:{hashlib.sha256(identity.encode()).hexdigest()[:32]}"


async def _store_question_answer(
    db: AsyncSession, channel: Channel, question: dict
) -> None:
    """Upsert one Q&A pair from Google's questions list.

    Google returns questions with optional answers. We store both the
    question and any merchant answer. Customer answers are read-only;
    only merchant answers are ever posted back to Google.
    """
    question_id = question.get("name", "")
    if not question_id:
        return

    existing = (
        await db.execute(
            select(GoogleQuestionAnswer).where(
                GoogleQuestionAnswer.channel_id == channel.id,
                GoogleQuestionAnswer.question_id == question_id,
            )
        )
    ).scalar_one_or_none()

    asker = question.get("author") or {}
    top_answers = question.get("topAnswers") or []
    merchant_answer = next(
        (
            a
            for a in top_answers
            if str(((a.get("author") or {}).get("type") or "")).upper() == "MERCHANT"
        ),
        None,
    )
    answer = merchant_answer or {}
    answer_text = (answer.get("text") or "").strip() or None
    answer_author = answer.get("author") or {}

    if existing is None:
        db.add(
            GoogleQuestionAnswer(
                id=str(uuid.uuid4()),
                user_id=channel.user_id,
                channel_id=channel.id,
                question_id=question_id,
                question_text=question.get("text", "") or "",
                asker_name=asker.get("displayName"),
                asker_profile_photo_url=asker.get("profilePhotoUrl"),
                question_created_at=_parse_google_time(question.get("createTime")),
                answer_text=answer_text,
                answerer_name=answer_author.get("displayName"),
                answer_type=answer_author.get("type"),
                answer_created_at=_parse_google_time(
                    answer.get("createTime") or answer.get("updateTime")
                ),
                is_answered=bool(answer_text),
                upvote_count=int(question.get("upvoteCount", 0) or 0),
                draft_status="posted" if answer_text else "none",
                draft_approved_at=(
                    _parse_google_time(answer.get("createTime"))
                    if answer_text
                    else None
                ),
                last_synced_at=datetime.now(timezone.utc),
            )
        )
    else:
        existing.question_text = question.get("text", "") or ""
        existing.asker_name = asker.get("displayName")
        existing.asker_profile_photo_url = asker.get("profilePhotoUrl")
        existing.question_created_at = _parse_google_time(
            question.get("createTime")
        )
        existing.answer_text = answer_text
        existing.answerer_name = answer_author.get("displayName")
        existing.answer_type = answer_author.get("type")
        existing.answer_created_at = _parse_google_time(
            answer.get("createTime") or answer.get("updateTime")
        )
        existing.is_answered = bool(answer_text)
        existing.upvote_count = int(question.get("upvoteCount", 0) or 0)
        if answer_text:
            existing.draft_status = "posted"
            existing.draft_approved_at = (
                existing.draft_approved_at
                or _parse_google_time(answer.get("createTime"))
            )
        existing.last_synced_at = datetime.now(timezone.utc)
        db.add(existing)


def _parse_google_time(value: str | None) -> datetime | None:
    """Parse a Google API RFC-3339 timestamp into an aware datetime."""
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None



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
    from ..outbox.service import enqueue_event_in

    await enqueue_event_in(
        db,
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


async def _enqueue_review_replied(
    db: AsyncSession,
    channel: Channel,
    review,
    status: str,
    replied_at: datetime | None = None,
) -> None:
    """Emit review.replied so analytics tracks response rate/time.

    An adopted Google reply carries the provider's `reviewReply.updateTime`,
    so response-time metrics use the real publish time instead of the moment
    Sayvors happened to import it.
    """
    from ..outbox.service import enqueue_event_in

    await enqueue_event_in(
        db,
        "review.replied",
        {
            "user_id": channel.user_id,
            "channel_id": channel.id,
            "review_id": review.review_id,
            "status": status,
            "replied_at": (replied_at or datetime.now(timezone.utc)).isoformat(),
        },
        topic=REVIEW_EVENTS_TOPIC,
    )
    await db.commit()


async def _announce_new_issue(
    db: AsyncSession, *, tenant_id: str, outcome: dict
) -> None:
    """Tell the merchant a ticket just appeared, and ring the bell once.

    Only ticketed issues are announced. A classified review with nothing to
    act on (praise, a passing question) is still stored, but pinging about it
    would train merchants to ignore ticket alerts — and the earlier decision
    is explicit: praise never becomes a ticket.

    Commits so the notification row survives: the poll loop's `continue`
    paths below skip the reply work entirely, and without this commit the
    insert would be rolled back with the session. Failures are swallowed —
    an unannounced ticket is a missed alert, not a failed poll.
    """
    from .models import ReviewIssue
    from .review_issue_events import notify_review_issue, publish_review_issue_event

    issue_id = outcome.get("issue_id")
    if not issue_id:
        return
    try:
        issue = (
            await db.execute(
                select(ReviewIssue).where(ReviewIssue.id == issue_id)
            )
        ).scalar_one_or_none()
        if issue is None or not issue.ticket_number:
            return
        await publish_review_issue_event(tenant_id, issue, "created")
        await notify_review_issue(db, tenant_id=tenant_id, issue=issue, action="created")
        await db.commit()
    except Exception as e:  # noqa: BLE001
        logger.warning("review ticket announcement failed for %s: %s", issue_id, e)


async def _refresh_edited_review_reply(
    db: AsyncSession, channel: Channel, config: AutoReplyConfig, review, client=None
) -> None:
    """Bring a queued/live response back in step with an edited review.

    Google polls return reviews updated since the last pass. When the text
    or rating changed after a reply was queued or posted, the response on
    file answers content that no longer exists: a still-pending draft is
    regenerated in place, and a posted reply gets a follow-up draft queued
    behind it. An edit follow-up waits for approval by default; the
    edited_review_autopost opt-in posts it through the same gates as a
    fresh reply (approval_mode "auto" + rating at/above min_rating_auto).
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
        reply_text, needs_review = await generate_auto_reply(
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
        await db.commit()
        return

    # posted/approved: an edit follow-up waits for a human by default.
    # With the merchant's opt-in it may auto-post, but only through the
    # same gates as a fresh reply: approval_mode "auto" and a rating
    # at/above min_rating_auto.
    autopost = (
        bool(getattr(config, "edited_review_autopost", False))
        and getattr(config, "approval_mode", "auto") != "approval"
        and review.rating >= config.min_rating_auto
    )
    status = "pending_approval"
    if autopost and client is not None:
        try:
            await client.reply_to_review(review.review_id, reply_text)
            if not await client.confirm_reply_live(review.review_id):
                raise GoogleReviewsError(
                    "Google accepted the reply but it is not showing on the listing"
                )
        except GoogleReviewsError as e:
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
            return
        status = "posted"
    _save_reply_row(
        db, failed_row, channel.id, review.review_id,
        review.rating, review.text, review.reviewer_name,
        reply_text, status,
    )
    if status == "posted":
        posted_row = (
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
        if posted_row is not None:
            await _store_reply_message(
                db, channel, review.review_id, review.reviewer_name,
                posted_row, status="sent", handled_by="ai",
            )
    if status == "posted":
        await notify(
            db, channel.user_id, "reply_posted",
            f"Auto-replied to ★{review.rating} review from {review.reviewer_name or 'a customer'}",
            (reply_text or "")[:160],
            data={"review_id": review.review_id, "channel_id": channel.id},
            href="/dashboard/reviews",
        )
    await db.commit()
    if status == "posted":
        try:
            await _enqueue_review_replied(db, channel, review, "posted")
        except Exception as e:
            logger.warning("review.replied enqueue failed for %s: %s", review.review_id, e)


async def process_channel(db: AsyncSession, channel: Channel, config: AutoReplyConfig) -> dict:
    """Poll one Google Reviews channel and auto-reply to new reviews."""
    stats = {"reviews": 0, "replied": 0, "queued": 0, "skipped": 0, "adopted": 0, "errors": 0}

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
        # A channel with no Google token is expected state (never connected,
        # or credentials cleared), not a failure — logging it at ERROR put
        # three identical lines in front of every real error, five minutes
        # apart, forever. Warn once per channel per process so a reconnect
        # problem stays visible without becoming the background noise.
        if channel.id not in _no_token_warned:
            _no_token_warned.add(channel.id)
            logger.warning(
                "Channel %s has no Google credentials stored; skipping its review poll",
                channel.id,
            )
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
        try:
            if not account_id or not location_id:
                # Fall back: list locations and use the first.
                locations = await client.list_locations(account_id) if account_id else []
                if not locations:
                    logger.warning("Channel %s: no account/location configured", channel.id)
                    return stats
                location_id = locations[0]["name"].split("/")[3]
            await _ensure_location_metadata(db, channel, client, location_id)
            if not _channel_meta(channel).get("reply_backfill_done"):
                try:
                    stats["adopted"] += await _backfill_existing_replies(
                        db, channel, client, account_id, location_id
                    )
                except Exception as e:
                    # A failed backfill is retried next poll; it must not stop
                    # normal review polling.
                    logger.warning(
                        "reply backfill failed for channel %s: %s", channel.id, e
                    )
            reviews = await client.list_reviews(
                account_id, location_id, updated_after=config.last_polled_at
            )
        except GoogleReviewsError as e:
            # A permanent rejection is not a transient error: the channel is
            # marked expired so it stops being polled, and the merchant is
            # told to reconnect.
            if e.status_code in PERMANENT_GOOGLE_STATUSES:
                await _mark_channel_expired(db, channel, str(e))
                await db.commit()
            raise

        await _mark_reviews_seen(db, channel, reviews)

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
            # Persist the structured classification so the WhatsApp handoff and
            # the "Status: Review" surface have facts to look up. Orchestrated by
            # the review pipeline graph (classify -> ticket -> handoff); it falls
            # back to running the same nodes inline if langgraph is unavailable.
            # Never break the auto-reply pipeline if classification fails (no
            # model, no network, unreachable provider) -- retried next poll.
            try:
                from ..channels.models import ReviewIssue
                from ..users.models import User
                from ..review_engine.graph import run_review_pipeline
                from ..channels.meta.lead_engine import normalize_lead_settings

                existing = await db.execute(
                    select(ReviewIssue).where(
                        ReviewIssue.channel_id == channel.id,
                        ReviewIssue.review_id == review.review_id,
                    ).limit(1)
                )
                if existing.scalar_one_or_none() is None:
                    model = getattr(config, "model", None)
                    if not model:
                        try:
                            from ..review_engine.service import _resolve_engine_model
                            from ..review_engine.schemas import ReviewEngineRequest
                            req = ReviewEngineRequest(rating=review.rating, channel_id=channel.id)
                            # Best-effort; ignored on failure.
                            model, _ = await _resolve_engine_model(
                                req,
                                channel.user_id,
                                db,
                            )
                        except Exception:
                            model = None
                    try:
                        urow = (await db.execute(
                            select(User.lead_settings).where(User.id == channel.user_id)
                        )).scalar_one_or_none()
                        subcats = normalize_lead_settings(urow).get(
                            "review_issue_subcategories"
                        ) or []
                    except Exception:
                        subcats = []
                    outcome = await run_review_pipeline(
                        db,
                        tenant_id=channel.user_id,
                        channel_id=channel.id,
                        review_id=review.review_id,
                        rating=review.rating,
                        review_text=review.text,
                        reviewer_name=review.reviewer_name,
                        model=model,
                        tenant_subcategories=subcats,
                    )
                    if outcome.get("classification_error"):
                        logger.warning(
                            "review issue classification failed for %s: %s",
                            review.review_id, outcome["classification_error"],
                        )
                    elif outcome.get("issue_created"):
                        logger.info(
                            "review issue %s -> ticket=%s handoff=%s code=%s",
                            review.review_id, outcome.get("ticket_number"),
                            outcome.get("handoff_eligible"),
                            outcome.get("handoff_code"),
                        )
                        await _announce_new_issue(
                            db, tenant_id=channel.user_id, outcome=outcome,
                        )
            except Exception as e:
                logger.warning("review issue classification failed for %s: %s", review.review_id, e)
            if await _adopt_existing_reply(db, channel, review):
                stats["adopted"] += 1
                stats["skipped"] += 1
                continue
            if await _already_replied(db, review.review_id):
                # Idempotency: a draft is already queued (or posted) for
                # this review — polling it again must not create a duplicate.
                # But if the reviewer edited the review since we replied or
                # queued a draft, first bring that response up to date.
                await _refresh_edited_review_reply(db, channel, config, review, client)
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
                reply_text, needs_review = await generate_auto_reply(
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
                or needs_review
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
                    await _enqueue_review_replied(db, channel, review, "posted")
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
                    await _enqueue_review_replied(db, channel, review, "pending_approval")
                except Exception as e:
                    logger.warning("review.replied enqueue failed for %s: %s", review.review_id, e)

        # A complete sweep is intentionally rare: the normal poll is
        # incremental, so removal detection needs one full read per day.
        meta = _channel_meta(channel)
        last_sweep = meta.get("removal_sweep_at")
        try:
            last_sweep_at = (
                datetime.fromisoformat(last_sweep) if last_sweep else None
            )
        except (TypeError, ValueError):
            last_sweep_at = None
        now = datetime.now(timezone.utc)
        if last_sweep_at is None or (now - last_sweep_at) > timedelta(hours=24):
            try:
                all_reviews = await client.list_reviews(account_id, location_id)
                seen_ids = {r.review_id for r in all_reviews}
                from .review_removal import mark_removed_reviews

                removed = await mark_removed_reviews(
                    db, channel, channel.user_id, seen_ids
                )
                meta["removal_sweep_at"] = now.isoformat()
                channel.metadata_json = json.dumps(meta)
                await db.commit()
                if removed:
                    logger.info(
                        "Removal sweep marked %d review(s) for channel %s",
                        len(removed), channel.id,
                    )
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    "Removal sweep failed for channel %s: %s", channel.id, e
                )

        # Google discontinued the My Business Q&A API on 2025-11-03. There
        # is no replacement; every native call now returns 404. Keep any
        # previously stored questions read-only and never poll Google again.
        # (`_store_question_answer` / `_qa_due` remain for the historical
        # tests and for imported rows, but the worker no longer calls them.)

        return stats
    finally:
        if client:
            await client.close()


_POLL_CONCURRENCY = 5


async def _poll_one_channel(
    channel_id: str,
    config_id: str,
    semaphore: asyncio.Semaphore,
) -> dict:
    """Poll one channel: claim → check backoff → process → release.

    Each channel gets its own DB session so concurrent polls don't share
    a transaction. The semaphore caps concurrent in-flight API calls to
    Google so we don't overwhelm the endpoint.
    """
    from ...database import async_session

    stats = {"channels": 0, "reviews": 0, "replied": 0, "queued": 0, "skipped": 0, "adopted": 0, "errors": 0}

    async with semaphore:
        async with async_session() as session:
            channel = await session.get(Channel, channel_id)
            config = await session.get(AutoReplyConfig, config_id)

            if channel is None or config is None:
                return stats

            if not await _claim_channel(session, config.id, config.last_polled_at):
                return stats  # another instance has it

            try:
                now = datetime.now(timezone.utc)

                # Channel health backoff: a channel Google is rate-limiting
                # gets breathing room instead of being retried every poll.
                if _is_in_health_backoff(channel, now):
                    logger.info(
                        "Channel %s in health backoff — skipping this poll pass",
                        channel.id,
                    )
                    await _release_channel(session, config.id)
                    return stats

                stats["channels"] += 1
                try:
                    channel_stats = await process_channel(session, channel, config)
                    for k in ("reviews", "replied", "queued", "skipped", "adopted", "errors"):
                        stats[k] += channel_stats[k]
                except Exception as e:
                    logger.error("Poll failed for channel %s: %s", channel.id, e)
                    stats["errors"] += 1
                    await _update_channel_health(session, channel, False, type(e).__name__)
                else:
                    await _update_channel_health(session, channel, True)
            finally:
                await _release_channel(session, config.id)

    return stats


async def poll_once() -> dict:
    """One polling pass over all due Google Reviews channels. Returns totals.

    Channels are polled concurrently (bounded by _POLL_CONCURRENCY) instead
    of serially, so a slow Google response on one channel doesn't block
    all the others.
    """
    from ...database import async_session

    totals = {"channels": 0, "reviews": 0, "replied": 0, "queued": 0, "skipped": 0, "adopted": 0, "errors": 0}
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

    channel_configs = [(str(ch.id), str(cfg.id)) for ch, cfg in rows]

    semaphore = asyncio.Semaphore(_POLL_CONCURRENCY)

    results = await asyncio.gather(
        *[
            _poll_one_channel(ch_id, cfg_id, semaphore)
            for ch_id, cfg_id in channel_configs
        ],
        return_exceptions=True,
    )

    for (ch_id, _cfg_id), result in zip(channel_configs, results):
        if isinstance(result, Exception):
            # Name the channel and keep the traceback: a bare "'channels'" told
            # nobody which channel broke or where, and the pass moved on.
            logger.error("Poll task failed for channel %s: %r", ch_id, result, exc_info=result)
            totals["errors"] += 1
        else:
            for k in ("channels", "reviews", "replied", "queued", "skipped", "adopted", "errors"):
                totals[k] += result[k]

    return totals


async def run_google_reviews_worker() -> None:
    """Background loop started from app lifespan."""
    while True:
        try:
            totals = await poll_once()
            if totals["reviews"] or totals["errors"]:
                logger.info("Google reviews poll: %s", totals)
        except Exception as e:
            logger.error("Google reviews poll pass failed: %s", e)
        await asyncio.sleep(max(30, settings.GOOGLE_REVIEWS_POLL_INTERVAL_SECONDS))

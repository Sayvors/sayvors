"""Localith service: thin wrapper around the spike adapter that returns
the real listings from your Localith account. Single-shared-key mode
for v1 — the API key is read from LOCALITH_API_KEY in the server env
and used for all connections. The (user_id, listing_id) mapping is
what we persist.

Full sync pulls everything the read API offers for the connected
listing: profile snapshot (detail), all review items (paginated),
performance metrics summary and review metrics summary.
"""

from __future__ import annotations

import asyncio
import json
import importlib.util
import logging
import sys
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from ..analytics.models import ReviewInsight
from ..channels.models import AutoReplyConfig, Channel, ReviewReply
from ..channels.review_reply import generate_auto_reply
from ..channels.reviews_worker import _resume_failed_row, _save_reply_row
from ..outbox.service import enqueue_event
from ..users.models import User

logger = logging.getLogger(__name__)

# services/api/app/modules/localith/service.py -> go up 4 dirs to services/api
_API_ROOT = Path(__file__).resolve().parents[4]
_REPO_ROOT = _API_ROOT.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# A two-stage import: load the .py, then install it as a real module
# with a stable import name. Spec from a file path requires the file to
# exist relative to a sys.path entry, but a file-path spec also works.
embedsocial = importlib.import_module("integrations.channels.embedsocial")  # type: ignore[arg-type]


def _key_present() -> bool:
    return bool(settings.LOCALITH_API_KEY.strip())


async def list_local_listings() -> list[dict]:
    """List Localith listings for the configured account. Raises on failure."""
    if not _key_present():
        raise RuntimeError("Server is missing LOCALITH_API_KEY in .env.")
    return await asyncio.to_thread(embedsocial.fetch_listings)


async def list_local_items(listing_id: str, limit: int = 50) -> list[dict]:
    """List Localith review items for one listing."""
    if not _key_present():
        raise RuntimeError("Server is missing LOCALITH_API_KEY in .env.")
    return await asyncio.to_thread(embedsocial.fetch_items, limit, listing_id)


async def get_listing_detail(listing_id: str) -> dict:
    """Fetch the full profile snapshot for one listing."""
    if not _key_present():
        raise RuntimeError("Server is missing LOCALITH_API_KEY in .env.")
    return await asyncio.to_thread(embedsocial.fetch_listing_detail, listing_id)


async def post_reply(item_id: str, text: str) -> dict:
    """Publish a reply to a review item through Localith.

    Their `POST /rest/v1/items/{id}/replies` posts the reply live on the
    connected Google Business Profile — this is how Localith-sourced
    drafts reach Google without native OAuth.
    """
    if not _key_present():
        raise RuntimeError("Server is missing LOCALITH_API_KEY in .env.")
    return await asyncio.to_thread(embedsocial.post_item_reply, item_id, text)


def _parse_dt(value: object) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _as_int(value: object, default: int = 0) -> int:
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return default


def _as_float(value: object, default: float = 0.0) -> float:
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return default


def _as_bool(value: object) -> bool | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes")
    return bool(value)


def apply_listing_snapshot(connection, raw: dict) -> None:
    """Copy a raw listing detail payload onto a LocalithConnection."""
    norm = embedsocial.normalize_listing(raw)
    connection.listing_name = norm["name"] or connection.listing_name
    if norm["google_id"]:
        connection.listing_google_id = str(norm["google_id"])
    connection.address = norm["address"]
    connection.phone_number = norm["phone_number"]
    connection.website_url = norm["website_url"]
    connection.maps_url = norm["maps_url"]
    connection.store_code = norm["store_code"]
    connection.is_verified = _as_bool(norm["is_verified"])
    connection.is_disabled = _as_bool(norm["is_disabled"])
    connection.is_suspended = _as_bool(norm["is_suspended"])
    connection.total_reviews = _as_int(norm["total_reviews"])
    connection.average_rating = _as_float(norm["average_rating"])
    connection.last_review_on = _parse_dt(norm["last_review_on"])
    connection.last_reply_on = _parse_dt(norm["last_reply_on"])
    connection.raw_listing_json = raw
    connection.profile_synced_at = datetime.now(timezone.utc)


async def list_connections(db: AsyncSession, user_id: str) -> list:
    """Every Localith listing row a tenant has connected (all branches)."""
    from .models import LocalithConnection

    result = await db.execute(
        select(LocalithConnection)
        .where(LocalithConnection.user_id == user_id)
        .order_by(LocalithConnection.created_at)
    )
    return list(result.scalars().all())


async def get_connection(
    db: AsyncSession, user_id: str, listing_id: str | None = None
):
    """One connection by listing, or the first connected branch (legacy callers)."""
    connections = await list_connections(db, user_id)
    if listing_id:
        return next((c for c in connections if c.listing_id == listing_id), None)
    return connections[0] if connections else None


async def sync_connection(
    user: User,
    db: AsyncSession,
    metrics_days_back: int = 30,
    listing_id: str | None = None,
) -> dict[str, int | str]:
    """Sync one tenant's Localith listing into Sayvors' normal review pipeline.

    With listing_id set, syncs exactly that branch; otherwise syncs every
    connected branch and aggregates totals. Other branches are never touched.

    Pulls everything the read API offers per branch:
      1. listing detail -> profile snapshot columns on the connection
      2. all review items (paginated) -> ReviewInsight rows + review events
      3. performance metrics summary (last N days) -> raw snapshot
      4. review metrics summary (last N days) -> raw snapshot
    """
    from .models import LocalithConnection  # noqa: F401 (re-export for callers)

    if listing_id is None:
        connections = await list_connections(db, user.id)
        if not connections:
            raise ValueError("Connect a Localith listing before syncing.")
        totals: dict[str, int | str] = {
            "fetched": 0, "new_reviews": 0, "branches": 0, "errors": 0,
        }
        for connection in connections:
            try:
                one = await _sync_single_connection(
                    user, db, connection, metrics_days_back
                )
                totals["fetched"] = int(totals["fetched"]) + int(one.get("fetched", 0))
                totals["new_reviews"] = int(totals["new_reviews"]) + int(one.get("new_reviews", 0))
                totals["branches"] = int(totals["branches"]) + 1
            except Exception as e:
                logger.error(
                    "Localith sync failed for listing %s: %s", connection.listing_id, e
                )
                totals["errors"] = int(totals["errors"]) + 1
                try:
                    await db.rollback()
                except Exception:
                    pass
        return totals

    connection = await get_connection(db, user.id, listing_id)
    if connection is None:
        raise ValueError("Connect a Localith listing before syncing.")
    return await _sync_single_connection(user, db, connection, metrics_days_back)


async def _sync_single_connection(
    user: User, db: AsyncSession, connection, metrics_days_back: int = 30
) -> dict[str, int | str]:

    channel_result = await db.execute(
        select(Channel).where(
            Channel.user_id == user.id,
            Channel.platform == "google_reviews",
            Channel.metadata_json.contains(connection.listing_id),
        )
    )
    channel = channel_result.scalar_one_or_none()
    if channel is None:
        channel = Channel(
            id=str(uuid.uuid4()),
            user_id=user.id,
            platform="google_reviews",
            platform_user_id=connection.listing_google_id or connection.listing_id,
            display_name=connection.listing_name,
            status="active",
            metadata_json=json.dumps({
                "provider": settings.BUSINESS_DATA_PROVIDER,
                "listing_id": connection.listing_id,
                "location_id": connection.listing_google_id or connection.listing_id,
            }),
        )
        db.add(channel)
        await db.flush()

    # 1. Profile snapshot — every field the detail endpoint returns.
    detail = await get_listing_detail(connection.listing_id)
    if detail:
        apply_listing_snapshot(connection, detail)
        channel.display_name = connection.listing_name
        channel.platform_user_id = connection.listing_google_id or connection.listing_id

    # 2. All review items, paginated (100/page, newest first).
    items = await asyncio.to_thread(
        embedsocial.fetch_all_items, connection.listing_id
    )
    synced = 0
    for item in items:
        review_id = str(item.get("id") or item.get("review_id") or item.get("uid") or "")
        if not review_id:
            continue
        review = embedsocial.to_internal_review(item)
        existing = await db.execute(
            select(ReviewInsight).where(
                ReviewInsight.channel_id == channel.id,
                ReviewInsight.review_id == f"localith:{review_id}",
            )
        )
        insight = existing.scalar_one_or_none()
        if insight is None:
            insight = ReviewInsight(
                id=str(uuid.uuid4()),
                user_id=user.id,
                channel_id=channel.id,
                review_id=f"localith:{review_id}",
                rating=review.rating,
                review_text=review.text,
                reviewer_name=review.reviewer,
                enrichment_status="pending",
                review_updated_at=datetime.now(timezone.utc),
            )
            if review.review_url:
                insight.review_url = review.review_url
            if review.has_replies:
                insight.replied = True
                insight.replied_at = datetime.now(timezone.utc)
            db.add(insight)
            synced += 1
        else:
            # Backfill fields that older syncs didn't capture (never
            # overwrites enriched/curated data — only fills gaps).
            touched = False
            if not insight.review_text and review.text:
                insight.review_text = review.text
                touched = True
            if not insight.reviewer_name and review.reviewer:
                insight.reviewer_name = review.reviewer
                touched = True
            if not insight.review_url and review.review_url:
                insight.review_url = review.review_url
                touched = True
            if review.has_replies and not insight.replied:
                insight.replied = True
                insight.replied_at = datetime.now(timezone.utc)
                touched = True
            if touched:
                synced += 1

    # 3+4. Metrics summaries over the trailing window.
    end = date.today()
    start = end - timedelta(days=max(1, metrics_days_back))
    metrics = await asyncio.to_thread(
        embedsocial.fetch_listing_metrics, start, end, connection.listing_id
    )
    item_metrics = await asyncio.to_thread(
        embedsocial.fetch_item_metrics, start, end, connection.listing_id
    )
    if metrics:
        connection.raw_metrics_json = metrics
    if item_metrics:
        connection.raw_item_metrics_json = item_metrics
    if metrics or item_metrics:
        connection.metrics_start = start
        connection.metrics_end = end
        connection.metrics_synced_at = datetime.now(timezone.utc)

    connection.last_synced_at = datetime.now(timezone.utc)
    await db.commit()

    # Reply drafts: Localith reviews flow through the same reply engine as
    # OAuth channels. Approving a draft posts it live via Localith's
    # POST /items/{id}/replies (see channels.router.approve_review_reply);
    # drafts queue as pending_approval until the merchant approves.
    # Cap per sync so a first-time backfill doesn't flood the queue with
    # LLM calls.
    DRAFT_CAP_PER_SYNC = 20
    config = (
        await db.execute(
            select(AutoReplyConfig).where(AutoReplyConfig.channel_id == channel.id)
        )
    ).scalar_one_or_none()
    if config is None:
        config = AutoReplyConfig(channel_id=channel.id)
        db.add(config)
        await db.flush()

    drafted = 0
    for item in items:
        if drafted >= DRAFT_CAP_PER_SYNC:
            break
        review_id = str(item.get("id") or item.get("review_id") or item.get("uid") or "")
        if not review_id:
            continue
        review = embedsocial.to_internal_review(item)
        if review.has_replies:
            continue
        full_review_id = f"localith:{review_id}"
        existing_reply = (
            await db.execute(
                select(ReviewReply.id).where(
                    ReviewReply.channel_id == channel.id,
                    ReviewReply.review_id == full_review_id,
                    ReviewReply.status.in_(["pending_approval", "posted", "approved"]),
                )
            )
        ).scalar_one_or_none()
        if existing_reply:
            continue
        # Don't generate drafts for reviews the merchant marked
        # as deleted/removed on Google.
        insight = (await db.execute(
            select(ReviewInsight).where(
                ReviewInsight.channel_id == channel.id,
                ReviewInsight.review_id == full_review_id,
            )
        )).scalar_one_or_none()
        if insight and insight.skipped:
            continue
        failed_row = await _resume_failed_row(db, channel.id, full_review_id)
        try:
            reply_text = await generate_auto_reply(
                config, channel, review.rating, review.text, review.reviewer, db,
                review_id=full_review_id,
                attempt=(failed_row.generation_attempt or 1) + 1 if failed_row else 1,
                previous_draft=failed_row.reply_text if failed_row else None,
            )
        except Exception as e:
            logger.warning("Localith draft generation failed review=%s: %s", review_id, e)
            # Surface the failure in the approval queue instead of letting the
            # review vanish — Retry regenerates once the LLM is reachable.
            _save_reply_row(
                db, failed_row, channel.id, full_review_id,
                review.rating, review.text, review.reviewer,
                "", "failed", str(e)[:2000],
            )
            await db.commit()
            continue
        # Auto Pilot: "auto" mode + rating >= threshold posts the reply live
        # through Localith immediately — the same publish path the Approve
        # button uses (POST /items/{id}/replies). Mock/dev mode never posts.
        auto_post = (
            config.approval_mode == "auto"
            and review.rating >= config.min_rating_auto
            and not settings.GOOGLE_REVIEWS_MOCK
        )
        if auto_post:
            try:
                await post_reply(review_id, reply_text)
            except Exception as e:
                logger.warning("Localith auto-post failed review=%s item=%s: %s", review_id, review_id, e)
                _save_reply_row(
                    db, failed_row, channel.id, full_review_id,
                    review.rating, review.text, review.reviewer,
                    reply_text, "failed", str(e)[:2000],
                )
                await db.commit()
                continue
            _save_reply_row(
                db, failed_row, channel.id, full_review_id,
                review.rating, review.text, review.reviewer,
                reply_text, "posted",
            )
            drafted += 1
            continue
        _save_reply_row(
            db, failed_row, channel.id, full_review_id,
            review.rating, review.text, review.reviewer,
            reply_text, "pending_approval",
        )
        drafted += 1
    if drafted:
        await db.commit()
        logger.info("Localith sync drafted %d replies for %s", drafted, connection.listing_id)

    for item in items:
        review_id = str(item.get("id") or item.get("review_id") or item.get("uid") or "")
        if not review_id:
            continue
        review = embedsocial.to_internal_review(item)
        full_review_id = f"localith:{review_id}"
        # Don't re-enqueue events for reviews the merchant
        # marked as unavailable on Google.
        _ins = (await db.execute(
            select(ReviewInsight).where(
                ReviewInsight.channel_id == channel.id,
                ReviewInsight.review_id == full_review_id,
            )
        )).scalar_one_or_none()
        if _ins and _ins.skipped:
            continue
        await enqueue_event(
            "review.discovered",
            {
                "user_id": user.id,
                "channel_id": channel.id,
                "review_id": f"localith:{review_id}",
                "rating": review.rating,
                "text": review.text,
                "reviewer_name": review.reviewer,
                "review_updated_at": review.published_at,
            },
            topic="review-events",
        )

    return {
        "channel_id": channel.id,
        "fetched": len(items),
        "new_reviews": synced,
        "profile_synced": bool(detail),
        "metrics_synced": bool(metrics or item_metrics),
        "metrics_start": start.isoformat(),
        "metrics_end": end.isoformat(),
    }


def now_utc() -> datetime:
    return datetime.now(timezone.utc)

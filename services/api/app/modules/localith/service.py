"""Localith service: thin wrapper around the spike adapter that returns
the real listings from your Localith account. Single-shared-key mode
for v1 — the API key is read from LOCALITH_API_KEY in the server env
and used for all connections. The (user_id, listing_id) mapping is
what we persist.
"""

from __future__ import annotations

import asyncio
import json
import importlib.util
import logging
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from ..analytics.models import ReviewInsight
from ..channels.models import Channel
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


async def sync_connection(user: User, db: AsyncSession) -> dict[str, int | str]:
    """Sync one tenant's Localith listing into Sayvors' normal review pipeline."""
    from .models import LocalithConnection

    result = await db.execute(
        select(LocalithConnection).where(LocalithConnection.user_id == user.id)
    )
    connection = result.scalar_one_or_none()
    if connection is None:
        raise ValueError("Connect a Localith listing before syncing.")

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

    items = await list_local_items(connection.listing_id, limit=500)
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
            db.add(insight)
            synced += 1

    connection.last_synced_at = datetime.now(timezone.utc)
    await db.commit()

    for item in items:
        review_id = str(item.get("id") or item.get("review_id") or item.get("uid") or "")
        if not review_id:
            continue
        review = embedsocial.to_internal_review(item)
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

    return {"channel_id": channel.id, "fetched": len(items), "new_reviews": synced}


def now_utc() -> datetime:
    return datetime.now(timezone.utc)

"""Follower snapshot worker.

Daily per active MetaAsset (FB page / IG account): reads the current
follower count from Meta's API and upserts it into the corresponding
channel's `channel_daily_metrics.followers_count` row for today. Runs
daily. Failures are isolated per asset — one bad token never kills the
pass.
"""
import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from ...config import settings
from ...database import async_session
from ..channels.models import Channel
from ..channels.meta.models import MetaAsset
from ..channels.meta.providers.facebook import FacebookAdapter
from ..channels.meta.providers.instagram import InstagramAdapter
from ..analytics.models import ChannelDailyMetric
from ..channels.service import decrypt_token

logger = logging.getLogger(__name__)

_INTERVAL = getattr(settings, "FOLLOWER_SNAPSHOT_INTERVAL_SECONDS", 86400)


async def _snapshot_asset(db, asset: MetaAsset) -> bool:
    """Read follower count for one asset and upsert into today's channel row.

    Returns True on success.
    """
    try:
        meta = asset.asset_metadata or {}
        token = meta.get("page_access_token") or meta.get("access_token")
        if not token:
            return False
        token = decrypt_token(token)

        count = None
        if asset.provider == "facebook" and asset.asset_type == "page":
            adapter = FacebookAdapter()
            profile = await adapter.get_page_profile(asset.external_asset_id, token)
            count = profile.get("fan_count") or profile.get("followers_count")
        elif asset.provider == "instagram" and asset.asset_type == "ig_account":
            adapter = InstagramAdapter()
            profile = await adapter.get_business_profile(asset.external_asset_id, token)
            count = profile.get("followers_count")

        if count is None:
            return False

        # Find the channel for this asset's tenant + platform.
        platform = "facebook" if asset.provider == "facebook" else "instagram"
        channel = (
            await db.execute(
                select(Channel).where(
                    Channel.user_id == asset.tenant_id,
                    Channel.platform == platform,
                    Channel.status == "active",
                )
            )
        ).scalars().first()
        if not channel:
            return False

        today = datetime.now(timezone.utc).date()
        row = (
            await db.execute(
                select(ChannelDailyMetric).where(
                    ChannelDailyMetric.channel_id == channel.id,
                    ChannelDailyMetric.date == today,
                )
            )
        ).scalar_one_or_none()
        if not row:
            row = ChannelDailyMetric(
                id=str(__import__("uuid").uuid4()),
                channel_id=channel.id,
                user_id=asset.tenant_id,
                date=today,
            )
            db.add(row)
        row.followers_count = int(count)
        row.computed_at = datetime.now(timezone.utc)
        await db.commit()
        return True
    except Exception as e:
        logger.warning("Follower snapshot failed for asset %s: %s", asset.id, e)
        await db.rollback()
        return False


async def snapshot_once(session_factory=None) -> dict:
    """One pass over all active FB/IG assets."""
    from ...database import async_session as default_factory

    factory = session_factory or default_factory
    totals = {"assets": 0, "snapshots": 0, "errors": 0}

    async with factory() as db:
        try:
            assets = (
                await db.execute(
                    select(MetaAsset).where(
                        MetaAsset.active == True,
                        MetaAsset.asset_type.in_(["page", "ig_account"]),
                    )
                )
            ).scalars().all()
        except Exception as e:
            logger.error("Follower snapshot: could not list assets: %s", e)
            totals["errors"] += 1
            return totals

        asset_ids = [a.id for a in assets]
        # Re-fetch each in its own session to avoid stale state.
        for aid in asset_ids:
            async with factory() as db:
                asset = await db.get(MetaAsset, aid)
                if asset is None:
                    continue
                totals["assets"] += 1
                ok = await _snapshot_asset(db, asset)
                if ok:
                    totals["snapshots"] += 1
                else:
                    totals["errors"] += 1

    return totals


async def run_follower_snapshot_worker() -> None:
    """Background loop. Runs snapshot_once daily."""
    logger.info("Follower snapshot worker started (interval=%ds)", _INTERVAL)
    while True:
        try:
            totals = await snapshot_once()
            logger.info("Follower snapshot pass: %s", totals)
        except Exception as e:
            logger.error("Follower snapshot worker error: %s", e)
        await asyncio.sleep(_INTERVAL)
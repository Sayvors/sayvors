"""Daily bounded synchronization of Meta's approximate WhatsApp spend facts."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ....database import async_session
from .credentials import decrypt_connection_token
from .models import MetaAsset
from .providers.whatsapp import WhatsAppAdapter
from .spend_store import upsert_spend_result

logger = logging.getLogger(__name__)
DAILY_INTERVAL_SECONDS = 24 * 60 * 60
ROLLING_DAYS = 7
MAX_BATCH = 200
MAX_CONCURRENCY = 4
MAX_FETCH_ATTEMPTS = 3
BACKOFF_SECONDS = (1, 2)


async def _fetch_with_retries(adapter, waba_id: str, token: str, start, end) -> dict:
    for attempt in range(MAX_FETCH_ATTEMPTS):
        try:
            return await adapter.get_pricing_analytics(
                waba_id, token, start=start, end=end
            )
        except Exception:
            if attempt == MAX_FETCH_ATTEMPTS - 1:
                raise
            await asyncio.sleep(BACKOFF_SECONDS[attempt])


def _with_asset_metadata(asset: MetaAsset, result: dict) -> dict:
    metadata = asset.asset_metadata or {}
    return {
        **result,
        "currency": result.get("currency") or metadata.get("currency"),
        "funding_mode": result.get("funding_mode") or metadata.get("funding_mode") or "unknown",
        "waba_timezone": result.get("waba_timezone") or metadata.get("timezone") or metadata.get("waba_timezone"),
        "messaging_account_id": (
            result.get("messaging_account_id")
            or metadata.get("messaging_account_id")
            or asset.external_asset_id
        ),
    }


async def sync_due_wabas(
    db=None, *, now: datetime | None = None, limit: int = MAX_BATCH,
    after_id: str = "",
) -> dict:
    """Refresh a keyset-bounded batch; no offset scan or unbounded fan-out."""
    now = now or datetime.now(timezone.utc)
    start = (now - timedelta(days=ROLLING_DAYS - 1)).date()
    end = now.date() + timedelta(days=1)  # Meta's end timestamp is exclusive.
    owns_session = db is None

    async def load_assets():
        query = (
            select(MetaAsset)
            .where(
                MetaAsset.provider == "whatsapp",
                MetaAsset.asset_type == "waba",
                MetaAsset.active.is_(True),
                MetaAsset.id > after_id,
            )
            .order_by(MetaAsset.id)
            .limit(max(1, min(limit, MAX_BATCH)))
            .options(selectinload(MetaAsset.connection))
        )
        return (await query_session.execute(query)).scalars().all()

    if owns_session:
        async with async_session() as query_session:
            assets = await load_assets()
    else:
        query_session = db
        assets = await load_assets()
    next_cursor = assets[-1].id if assets else ""

    semaphore = asyncio.Semaphore(MAX_CONCURRENCY)
    store_lock = asyncio.Lock()
    adapter = WhatsAppAdapter()

    async def sync_one(asset):
        async with semaphore:
            try:
                token = decrypt_connection_token(asset.connection) if asset.connection else None
                if not token:
                    raise RuntimeError("missing WhatsApp connection token")
                result = await _fetch_with_retries(
                    adapter, asset.external_asset_id, token, start, end
                )
                result = _with_asset_metadata(asset, result)
                if owns_session:
                    async with async_session() as store_session:
                        written = await upsert_spend_result(
                            store_session, asset.tenant_id,
                            asset.external_asset_id, result,
                        )
                else:
                    async with store_lock:
                        written = await upsert_spend_result(
                            query_session, asset.tenant_id,
                            asset.external_asset_id, result,
                        )
                return {"synced": 1, "facts": written, "errors": 0}
            except Exception as exc:
                logger.warning(
                    "WhatsApp spend sync failed waba=%s: %s",
                    asset.external_asset_id, type(exc).__name__,
                )
                return {"synced": 0, "facts": 0, "errors": 1}

    try:
        outcomes = await asyncio.gather(*(sync_one(asset) for asset in assets))
    finally:
        await adapter.close()
    return {
        **{key: sum(item[key] for item in outcomes) for key in ("synced", "facts", "errors")},
        "next_cursor": next_cursor,
    }


async def run_whatsapp_spend_worker() -> None:
    cursor = ""
    while True:
        try:
            result = await sync_due_wabas(after_id=cursor)
            logger.info("WhatsApp spend sync: %s", result)
            cursor = result["next_cursor"]
            if cursor:
                # Drain the bounded keyset pages, then wait for the next daily
                # cycle. Every active WABA is visited without an offset scan.
                continue
        except Exception:
            logger.exception("WhatsApp spend sync pass failed")
        await asyncio.sleep(DAILY_INTERVAL_SECONDS)

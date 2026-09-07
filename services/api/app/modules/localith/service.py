"""Localith service: thin wrapper around the spike adapter that returns
the real listings from your Localith account. Single-shared-key mode
for v1 — the API key is read from LOCALITH_API_KEY in the server env
and used for all connections. The (user_id, listing_id) mapping is
what we persist.
"""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from app.config import settings

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


def now_utc() -> datetime:
    return datetime.now(timezone.utc)

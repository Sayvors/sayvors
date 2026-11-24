"""Egress routing for the free Google endpoints (search, place detail, reviews).

All three adapters call Google directly, so Google sees the caller's IP. Once
that IP is rate-limited or blocked every place fails at once. This module is
the single seam that decides which route a request takes:

- **No proxies configured** (default): one direct route, exactly today's
  behaviour. Nothing to deploy, nothing to break.
- **Proxies configured** (``GOOGLE_SCRAPER_PROXIES``): the route is *sticky*
  per place or query, so one scrape keeps one IP. That matters for reviews:
  BOQ pagination tokens are tied to the session that started them, so hopping
  mid-way would restart the paging. A route that gets blocked goes into a short
  cooldown and is skipped for other places meanwhile.
- **Never direct once proxies exist.** Falling back to the server IP during a
  block is how a block becomes permanent, so the server IP is only used when no
  proxy was ever configured.

The pool is in-memory per worker process on purpose: a shared health registry
would need coordination for a problem that is already scoped to one process.
"""
from __future__ import annotations

import hashlib
import logging
import time
from typing import Any

import httpx

from ...config import settings

logger = logging.getLogger(__name__)

# How long a blocked proxy is left alone before it is tried again.
PROXY_COOLDOWN_SECONDS = 5 * 60
SUPPORTED_PROXY_SCHEMES = ("http://", "https://", "socks5://", "socks5h://")

# route -> {"cooldown_until": monotonic seconds}. Only cooling routes are kept.
_state: dict[str, float] = {}


def _now() -> float:
    return time.monotonic()


def proxies() -> list[str]:
    """Configured proxies, de-duplicated and in configuration order."""
    raw = str(getattr(settings, "GOOGLE_SCRAPER_PROXIES", "") or "")
    out: list[str] = []
    for part in raw.split(","):
        candidate = part.strip()
        if not candidate:
            continue
        if not candidate.startswith(SUPPORTED_PROXY_SCHEMES):
            # Never log the value: it can carry proxy credentials.
            logger.warning("Ignoring a malformed Google scraper proxy entry")
            continue
        if candidate not in out:
            out.append(candidate)
    return out


def routes_for(key: str) -> list[str | None]:
    """Ordered egress routes for one place/query: sticky first, then the rest.

    ``None`` means a direct connection and is only ever returned when no proxy
    is configured.
    """
    pool = proxies()
    if not pool:
        return [None]
    start = int(hashlib.sha1(str(key).encode("utf-8")).hexdigest(), 16) % len(pool)
    ordered = pool[start:] + pool[:start]
    now = _now()
    healthy = [route for route in ordered if _state.get(route, 0.0) <= now]
    # If everything is cooling down, still offer the proxies: retrying a tired
    # one beats scraping nothing, and it still protects the server IP.
    return healthy or ordered


def note_result(route: str | None, *, ok: bool) -> None:
    """Record whether a route worked, so a blocked one is rested."""
    if not route:
        return
    if ok:
        _state.pop(route, None)
        return
    _state[route] = _now() + PROXY_COOLDOWN_SECONDS
    logger.warning(
        "Google scraper proxy route blocked; resting it for %ss",
        PROXY_COOLDOWN_SECONDS,
    )


def client_for(route: str | None, *, timeout: float) -> httpx.AsyncClient:
    """One client bound to one route. Keep it for the whole request sequence."""
    kwargs: dict[str, Any] = {"timeout": timeout, "follow_redirects": True}
    if not route:
        return httpx.AsyncClient(**kwargs)
    try:
        # httpx 0.28 renamed ``proxies`` to ``proxy``.
        return httpx.AsyncClient(proxy=route, **kwargs)
    except TypeError:
        # The project declares httpx>=0.27, so keep that range working.
        return httpx.AsyncClient(proxies=route, **kwargs)


class Blocked(Exception):
    """Google refused this route (rate limit, consent wall, empty body).

    Raised by the adapters so ``routes_for`` can move to the next proxy. A
    changed payload layout is not a block and must not raise this.
    """

    def __init__(self, message: str, status_code: int = 503):
        self.status_code = status_code
        super().__init__(message)

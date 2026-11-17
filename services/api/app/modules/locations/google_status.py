"""Cached Google edit-status snapshots for the Locations page.

The page shows Google's real per-field edit lifecycle (pending / accepted /
rejected / updated-by-Google) plus the values live on Maps, and refreshes it
while the page is open. The Business Information API's default project quota
is 300 requests per minute, so polling has to be mediated. This module is that
mediator, and it spends as few calls as the API allows:

* ``:getExtended`` carries the merchant values, the consumer values **and**
  the per-field edit status in one response — and ``serviceItems`` is a
  top-level Location field, so the service list usually rides along instead
  of costing its own request.
* Attributes are the one thing Google keeps on a separate resource
  (``attributes:getExtended``), so they are the second call — and they are
  reused for ``GBP_STATUS_ATTRIBUTES_SECONDS`` because they only change when
  the merchant edits them.
* A project without the alpha channel is remembered for
  ``ALPHA_RETRY_SECONDS``: paying for the same 404 every minute would halve
  the useful budget on exactly the projects with the least to spend.

Layered on top of that:

* ``snapshot()`` serves any snapshot younger than its TTL, so every open tab
  on a branch shares one Google fan-out instead of one per viewer.
* Concurrent cache misses collapse behind a per-branch lock: one caller
  refreshes, the rest wait briefly and read the fresh value.
* Every Google call is charged to a per-minute counter capped by
  ``settings.GBP_STATUS_QPM_BUDGET``. When it is spent the last snapshot is
  served — stale but timestamped — and the UI says when it was checked.
  Polling can therefore never starve publishing, reviews or media, and a
  quota increase is a config change (raise the budget), not a code change.
* Failures are cached for ``FAILURE_RETRY_SECONDS`` so a broken endpoint is
  not retried by every open tab.

Redis is the shared store. If it is unreachable the module falls back to a
per-process cache and counter: still correct, but each worker keeps its own
copy and its own budget.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone

from ...config import settings
from ..redis.client import get_redis

logger = logging.getLogger(__name__)

CACHE_PREFIX = "gbp:status:"
LOCK_PREFIX = "gbp:status:lock:"
BUDGET_PREFIX = "gbp:qpm:"
ALPHA_OFF_PREFIX = "gbp:status:alpha_off:"

# Cadence the UI polls Sayvors at. The server decides between them: while an
# edit is in review there is something to watch; once every section is
# accepted, polling faster than this only spends quota.
ACTIVE_POLL_SECONDS = 60
IDLE_POLL_SECONDS = 300

# A failed refresh (network, auth, Google 5xx) is not an answer; retry it
# soon, but not once per open tab in the same minute.
FAILURE_RETRY_SECONDS = 30

# A connection that cannot use the v1alpha channel is remembered for this
# long. Asking again costs a quota unit each time and the answer only changes
# when Google enables the API or the merchant reconnects.
ALPHA_RETRY_SECONDS = 600

# Responses that mean "this project/connection cannot use the alpha channel".
# Anything else is a real failure and must surface.
ALPHA_UNAVAILABLE_STATUSES = (400, 403, 404)

# Cross-worker refresh lock. The holder is doing at most two HTTP calls, so
# 10s is generous; a crashed holder must not block refreshes forever.
LOCK_TTL_SECONDS = 10
LOCK_WAIT_SECONDS = 2.0
LOCK_POLL_INTERVAL_SECONDS = 0.05

# readMask for the stable-v1 fallback. It must cover every field whose
# edit status the page can show, because ``diffMask`` only reports fields
# present in the mask.
STATUS_READ_MASK = ",".join(
    [
        "name",
        "phoneNumbers",
        "websiteUri",
        "categories",
        "regularHours",
        "specialHours",
        "moreHours",
        "serviceArea",
        "profile",
        "openInfo",
        "storefrontAddress",
        "serviceItems",
    ]
)

# Worst stage first; a section that mixes stages (attributes hold one stage
# per attribute) reports the worst.
STAGE_RANK = {
    "rejected": 0,
    "pending": 1,
    "google_updated": 2,
    "draft": 3,
    "accepted": 4,
    "unspecified": 5,
}

# Bounds for the process-local fallback so a long-lived worker cannot grow
# these without limit.
_MAX_PROCESS_ENTRIES = 512
_MAX_LOCKS = 512

_PROCESS_CACHE: dict[str, tuple[float, dict]] = {}
_PROCESS_BUDGET: dict[str, int] = {}
# channel key -> (expires_at, status code that proved alpha unavailable)
_PROCESS_ALPHA_OFF: dict[str, tuple[float, int]] = {}
_INFLIGHT_LOCKS: dict[tuple[int, str], asyncio.Lock] = {}


class BudgetExhausted(Exception):
    """The per-minute edit-status budget is spent; serve cache instead."""


class StatusUnavailable(Exception):
    """No status can exist yet (no OAuth tokens) — not an error to retry hard."""


def reset_process_state() -> None:
    """Drop the per-process cache/counter (tests, and the ``reload`` path)."""
    _PROCESS_CACHE.clear()
    _PROCESS_BUDGET.clear()
    _PROCESS_ALPHA_OFF.clear()
    _INFLIGHT_LOCKS.clear()


async def invalidate(channel, listing_id: str) -> None:
    """Drop the cached snapshot for one branch after a successful write.

    Left in place, the pre-save snapshot would keep reporting the previous
    stage for up to its TTL, telling the merchant Google accepted an edit it
    has not seen yet.
    """
    key = _cache_key(channel, listing_id)
    _PROCESS_CACHE.pop(key, None)
    redis = await _redis()
    if redis is None:
        return
    try:
        await redis.delete(CACHE_PREFIX + key)
    except Exception as e:  # noqa: BLE001 — a stale TTL is not worth failing a save
        logger.debug("Edit-status cache invalidate failed: %s", e)


async def snapshot(channel, listing_id: str, *, force: bool = False) -> dict:
    """Google's edit status for one branch, cached and budgeted.

    ``force`` skips the freshness check (the UI's "Check now") but still
    respects the budget and the single-flight lock — a manual refresh must
    not let one user burn the project's quota.

    Returns the API/UI view: ``sections``, ``current``, ``checked_at``,
    ``age_seconds``, ``source`` (live / cache / stale / unavailable),
    ``alpha_available``, ``reason`` and ``next_poll_after``.
    """
    key = _cache_key(channel, listing_id)
    now = time.time()
    cached = await _cache_get(key)
    if cached is not None and not force and _is_fresh(cached, now):
        return _view(cached, "cache", now)

    async with _lock_for(key):
        # Another request may have refreshed while we waited for the lock.
        cached = await _cache_get(key)
        if cached is not None and not force and _is_fresh(cached, now):
            return _view(cached, "cache", now)

        redis = await _redis()
        owns_remote_lock = True
        if redis is not None:
            owns_remote_lock = await _acquire_remote_lock(redis, key)
        if not owns_remote_lock:
            # A different worker is refreshing: wait for its snapshot instead
            # of duplicating the Google fan-out.
            waited = await _wait_for_snapshot(key)
            if waited is not None:
                return _view(waited, "cache", now)

        try:
            sections, current, attributes_at, alpha, reason = await _fetch(
                channel, listing_id, cached
            )
            snap = {
                "ok": True,
                "sections": sections,
                "current": current,
                "fetched_at": time.time(),
                "attributes_at": attributes_at,
                "alpha": alpha,
                "reason": reason,
                "ttl": _ttl_for(sections),
            }
            await _cache_set(key, snap)
            return _view(snap, "live", time.time())
        except BudgetExhausted:
            logger.info(
                "Edit-status budget spent; serving cached snapshot for %s", listing_id
            )
            if cached is not None:
                return _view(cached, "stale", now)
            return _unavailable("budget")
        except StatusUnavailable as e:
            reason = str(e)
            if cached is not None:
                # Last known status is still the honest answer while the
                # channel cannot be read; the age tells the merchant.
                return _view(cached, "stale", now)
            await _cache_set(
                key,
                {
                    "ok": False,
                    "sections": {},
                    "current": {},
                    "fetched_at": time.time(),
                    "alpha": False,
                    "reason": reason,
                    "ttl": FAILURE_RETRY_SECONDS,
                },
            )
            return _unavailable(reason)
        except Exception as e:  # noqa: BLE001 — status must never break the page
            logger.warning("Google edit status failed for %s: %s", listing_id, e)
            failure = {
                "ok": False,
                "sections": {},
                "current": {},
                "fetched_at": time.time(),
                "alpha": False,
                "reason": "error",
                "ttl": FAILURE_RETRY_SECONDS,
            }
            # Cache the failure so every open tab does not retry it. A good
            # snapshot is left alone: rewriting it here would shorten its own
            # TTL to the failure backoff.
            if cached is None:
                await _cache_set(key, failure)
            else:
                return _view(cached, "stale", now)
            return _unavailable("error")
        finally:
            if owns_remote_lock and redis is not None:
                await _release_remote_lock(redis, key)


# ── View shaping ─────────────────────────────────────────────────────────


def _view(snap: dict, source: str, now: float) -> dict:
    """Snapshot → the response shape, with its age and the next poll delay."""
    ok = bool(snap.get("ok", True))
    sections = snap.get("sections") or {}
    fetched_at = snap.get("fetched_at")
    age = int(max(0, now - fetched_at)) if isinstance(fetched_at, (int, float)) else None
    return {
        "sections": sections if ok else {},
        "current": (snap.get("current") or {}) if ok else {},
        "checked_at": _iso(fetched_at) if ok and fetched_at else None,
        "age_seconds": age,
        "alpha_available": bool(snap.get("alpha")),
        "reason": snap.get("reason"),
        "source": source if ok else "unavailable",
        "next_poll_after": _poll_delay(sections) if ok else IDLE_POLL_SECONDS,
    }


def _unavailable(reason: str) -> dict:
    return {
        "sections": {},
        "current": {},
        "checked_at": None,
        "age_seconds": None,
        "alpha_available": False,
        "reason": reason,
        "source": "unavailable",
        "next_poll_after": IDLE_POLL_SECONDS,
    }


def _poll_delay(sections: dict) -> int:
    for entry in sections.values():
        if isinstance(entry, dict) and entry.get("stage") in ("pending", "draft"):
            return ACTIVE_POLL_SECONDS
    return IDLE_POLL_SECONDS


def _ttl_for(sections: dict) -> int:
    """Cache lifetime: short while reviewing, long once everything is live.

    A pending edit is the only reason to poll every minute, so an accepted
    profile costs one refresh per five minutes instead of one per minute.
    """
    active = _poll_delay(sections) == ACTIVE_POLL_SECONDS
    return max(
        5,
        settings.GBP_STATUS_CACHE_SECONDS if active else settings.GBP_STATUS_IDLE_SECONDS,
    )


def _is_fresh(snap: dict, now: float) -> bool:
    fetched_at = snap.get("fetched_at")
    if not isinstance(fetched_at, (int, float)):
        return False
    ttl = snap.get("ttl")
    if not isinstance(ttl, (int, float)):
        ttl = settings.GBP_STATUS_CACHE_SECONDS
    return (now - fetched_at) < ttl


def _iso(ts: float | None) -> str | None:
    if not isinstance(ts, (int, float)):
        return None
    return (
        datetime.fromtimestamp(ts, timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


# ── Google fetch ─────────────────────────────────────────────────────────


async def _fetch(
    channel, listing_id: str, previous: dict | None = None
) -> tuple[dict, dict, float | None, bool, str | None]:
    """One refresh: alpha edit status, falling back to the stable v1 masks.

    Returns ``(sections, current, attributes_at, alpha_available, reason)``.
    ``previous`` is the snapshot this refresh replaces; it lets the alpha path
    reuse an attribute reading that is still fresh instead of paying for the
    same answer again.
    """
    from ..channels.google_business import GoogleBusinessClient
    from ..channels.google_reviews import GoogleReviewsError
    from ..channels.service import decrypt_token

    access = decrypt_token(channel.access_token) if channel.access_token else None
    refresh = decrypt_token(channel.refresh_token) if channel.refresh_token else None
    if not access and not refresh:
        # Nothing to authenticate with: not an error, just no status yet.
        raise StatusUnavailable("not_connected")

    client = GoogleBusinessClient(access or "", refresh)
    try:
        known = await _alpha_unavailable(channel)
        if known is not None:
            # This connection already proved it has no alpha channel. Asking
            # again would spend a quota unit to re-learn the same 404.
            sections, current = await _fetch_stable(client, listing_id)
            return sections, current, None, False, f"alpha_{known}"
        try:
            sections, current, attributes_at = await _fetch_alpha(
                client, listing_id, previous
            )
            return sections, current, attributes_at, True, None
        except GoogleReviewsError as e:
            # 400/403/404 mean the alpha channel is not enabled for this
            # project or app; the stable masks still answer "is it pending"
            # and "what differs on Maps".
            if e.status_code in ALPHA_UNAVAILABLE_STATUSES:
                logger.info(
                    "Edit-status alpha unavailable for %s (%s); using stable v1",
                    listing_id,
                    e.status_code,
                )
                await _remember_alpha_unavailable(channel, e.status_code)
                sections, current = await _fetch_stable(client, listing_id)
                return sections, current, None, False, f"alpha_{e.status_code}"
            raise
    finally:
        await client.close()


async def _fetch_alpha(
    client, listing_id: str, previous: dict | None = None
) -> tuple[dict, dict, float | None]:
    """Full per-field lifecycle from the v1alpha endpoints.

    ``:getExtended`` answers the merchant values, the live values **and** the
    per-field status in one response, so the common case is a single call: the
    service list rides along, and attributes are only re-read when the last
    reading is old enough to be worth a request.
    """
    from ..channels.google_business import parse_consumer_values, parse_edit_status

    if not await _take_budget():
        raise BudgetExhausted
    extended = await client.get_extended_location(listing_id)
    sections = parse_edit_status(extended)
    current = parse_consumer_values(extended)

    attributes_at = await _refresh_attributes(
        client, listing_id, sections, current, previous
    )

    # ``serviceItems`` is a top-level Location field, so the extended response
    # usually carries it and a separate request would buy nothing.
    inline, services = _services_from_extended(extended)
    if inline:
        current["services"] = services
    elif await _take_budget():
        try:
            service_items = await client.get_service_items(listing_id)
        except Exception as e:  # noqa: BLE001 — services are optional
            logger.debug("Service items unavailable for %s: %s", listing_id, e)
            service_items = []
        current["services"] = _service_items_summary(service_items)

    return sections, current, attributes_at


async def _refresh_attributes(
    client,
    listing_id: str,
    sections: dict,
    current: dict,
    previous: dict | None,
) -> float | None:
    """Fill the attributes section, reusing the last reading when it is fresh.

    Attributes are the one part of the profile Google keeps on a separate
    resource, and they change only when the merchant edits them — every push
    that touches them invalidates this snapshot. Re-reading a clean profile
    every minute discovers nothing and costs a quota unit, so a settled
    reading is reused for ``GBP_STATUS_ATTRIBUTES_SECONDS`` while a pending
    one keeps the one-minute cadence.

    Returns when Google last reported the attributes (None when this refresh
    has no usable attribute reading).
    """
    from ..channels.google_business import (
        parse_attribute_edit_status,
        parse_attribute_values,
    )

    if _attributes_reusable(previous, time.time()):
        prev = previous or {}
        prev_sections = prev.get("sections") or {}
        prev_current = prev.get("current") or {}
        if "attributes" in prev_sections:
            sections["attributes"] = prev_sections["attributes"]
        if "attributes" in prev_current:
            current["attributes"] = prev_current["attributes"]
        return prev.get("attributes_at")

    if not await _take_budget():
        return None
    try:
        attributes_extended = await client.get_extended_attributes(listing_id)
    except Exception as e:  # noqa: BLE001 — attributes are optional
        logger.debug("Attribute edit status unavailable for %s: %s", listing_id, e)
        return None

    # One section, worst attribute wins: a rejected Wi-Fi flag must not be
    # hidden behind an accepted one.
    folded = _fold_attribute_status(parse_attribute_edit_status(attributes_extended))
    if folded:
        sections["attributes"] = folded
    attribute_values = parse_attribute_values(attributes_extended)
    if attribute_values:
        current["attributes"] = attribute_values
    return time.time()


def _attributes_reusable(previous: dict | None, now: float) -> bool:
    """Whether the previous snapshot's attribute reading still stands.

    A pending attribute keeps the minute cadence — its acceptance is what the
    merchant is watching for. Anything else is reused for
    ``GBP_STATUS_ATTRIBUTES_SECONDS``.
    """
    if not previous or not previous.get("ok"):
        return False
    at = previous.get("attributes_at")
    if not isinstance(at, (int, float)):
        return False
    entry = (previous.get("sections") or {}).get("attributes") or {}
    pending = entry.get("stage") in ("pending", "draft")
    ttl = ACTIVE_POLL_SECONDS if pending else settings.GBP_STATUS_ATTRIBUTES_SECONDS
    return (now - at) < ttl


def _services_from_extended(extended: dict) -> tuple[bool, list[dict]]:
    """The service list carried by the ExtendedLocation payload, if present.

    ``serviceItems`` is a top-level Location field, not a resource of its own,
    so one extended read normally answers it. Returns ``(found, items)``;
    ``found`` is False when neither view carries the field, which is **not**
    proof of an empty list — the caller still asks for it in that case.
    """
    extended = extended if isinstance(extended, dict) else {}
    for view in ("locationProvidedByMerchant", "locationSeenByConsumers"):
        data = extended.get(view)
        if isinstance(data, dict) and "serviceItems" in data:
            items = data.get("serviceItems")
            return True, _service_items_summary(items if isinstance(items, list) else [])
    return False, []


async def _fetch_stable(client, listing_id: str) -> tuple[dict, dict]:
    """Coarse status from v1: pendingMask + diffMask, no stage or reason.

    Absence from both masks is *not* proof of acceptance, so those sections
    are simply omitted rather than reported as accepted.
    """
    from ..channels.google_business import masks_to_sections, parse_consumer_values

    if not await _take_budget():
        raise BudgetExhausted
    data = await client.get_google_updated(listing_id, STATUS_READ_MASK)
    pending = masks_to_sections(data.get("pendingMask"))
    changed = masks_to_sections(data.get("diffMask"))

    sections: dict[str, dict] = {}
    for section in pending:
        sections[section] = {
            "stage": "pending",
            "rejection_reason": None,
            "update_time": None,
            "source": None,
        }
    for section in changed - pending:
        sections[section] = {
            "stage": "google_updated",
            "rejection_reason": None,
            "update_time": None,
            "source": None,
        }

    location = data.get("location") or {}
    current = parse_consumer_values({"locationSeenByConsumers": location})
    services = _service_items_summary(location.get("serviceItems") or [])
    if services:
        current["services"] = services
    return sections, current


def _fold_attribute_status(per_attribute: dict[str, dict]) -> dict | None:
    """One section entry from per-attribute statuses: the worst stage wins."""
    if not per_attribute:
        return None
    worst = min(
        per_attribute.values(),
        key=lambda entry: STAGE_RANK.get(str(entry.get("stage")), 9),
    )
    return {
        "stage": worst.get("stage", "unspecified"),
        "rejection_reason": worst.get("rejection_reason"),
        "update_time": worst.get("update_time"),
        "source": worst.get("source"),
    }


def _service_items_summary(items: list[dict] | None) -> list[dict]:
    """Google's service items as ``[{name, offered}]`` for the UI."""
    out: list[dict] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        free = item.get("freeFormServiceItem") or {}
        label = free.get("label") or {}
        name = str(label.get("displayName") or "").strip()
        if name:
            out.append({"name": name, "offered": True})
            continue
        structured = item.get("structuredServiceItem") or {}
        service_id = str(structured.get("serviceTypeId") or "").strip()
        if service_id:
            out.append(
                {"name": service_id.split(":")[-1].replace("_", " "), "offered": True}
            )
    return out


# ── Quota budget ─────────────────────────────────────────────────────────


async def _take_budget() -> bool:
    """Charge one Google call to this minute's edit-status budget.

    The default project quota is 300 QPM for the whole Business Information
    API; polling gets only ``GBP_STATUS_QPM_BUDGET`` of it. When Redis is
    down each worker enforces the budget locally, so N workers can spend up
    to N × the budget — degraded, never unbounded.
    """
    limit = max(0, int(settings.GBP_STATUS_QPM_BUDGET))
    if limit == 0:
        return False
    minute = str(int(time.time() // 60))
    redis = await _redis()
    if redis is not None:
        try:
            key = BUDGET_PREFIX + minute
            used = await redis.incr(key)
            if used == 1:
                await redis.expire(key, 120)
            return used <= limit
        except Exception as e:  # noqa: BLE001 — fall through to process counter
            logger.debug("Edit-status budget counter unavailable: %s", e)
    if minute not in _PROCESS_BUDGET:
        _PROCESS_BUDGET.clear()
    used = _PROCESS_BUDGET.get(minute, 0) + 1
    _PROCESS_BUDGET[minute] = used
    return used <= limit


# ── Cache / lock plumbing ────────────────────────────────────────────────


def _channel_key(channel) -> str:
    return str(getattr(channel, "id", None) or "unknown")


async def _alpha_unavailable(channel) -> int | None:
    """The status code that proved this connection has no alpha channel.

    Google only changes that answer when the API gets enabled on the project
    or the merchant reconnects, so the marker expires rather than latching.
    """
    key = _channel_key(channel)
    redis = await _redis()
    if redis is not None:
        try:
            raw = await redis.get(ALPHA_OFF_PREFIX + key)
            return int(raw) if raw else None
        except Exception as e:  # noqa: BLE001 — fall back to the local marker
            logger.debug("Alpha-unavailable marker unreadable: %s", e)
    entry = _PROCESS_ALPHA_OFF.get(key)
    if entry is None:
        return None
    expires_at, status = entry
    if expires_at <= time.time():
        _PROCESS_ALPHA_OFF.pop(key, None)
        return None
    return status


async def _remember_alpha_unavailable(channel, status_code: int) -> None:
    """Stop paying for an alpha call we already know will fail."""
    key = _channel_key(channel)
    now = time.time()
    # The dict is keyed by channel, so drop expired markers before adding
    # another: a long-lived worker would otherwise keep one per channel.
    for stale_key, (expires_at, _) in list(_PROCESS_ALPHA_OFF.items()):
        if expires_at <= now:
            _PROCESS_ALPHA_OFF.pop(stale_key, None)
    _PROCESS_ALPHA_OFF[key] = (now + ALPHA_RETRY_SECONDS, status_code)
    redis = await _redis()
    if redis is None:
        return
    try:
        await redis.set(
            ALPHA_OFF_PREFIX + key, str(status_code), ex=ALPHA_RETRY_SECONDS
        )
    except Exception as e:  # noqa: BLE001 — the process marker still applies
        logger.debug("Alpha-unavailable marker write failed: %s", e)


def _cache_key(channel, listing_id: str) -> str:
    channel_id = getattr(channel, "id", None) or "unknown"
    return f"{channel_id}:{listing_id}"


async def _redis():
    """The shared client, or None when Redis is disabled/unreachable.

    Tests set ``settings.TESTING``; they must never open a socket here.
    """
    if settings.TESTING:
        return None
    try:
        return await get_redis()
    except Exception as e:  # noqa: BLE001 — cache is optional, the page is not
        logger.debug("Redis unavailable for edit-status cache: %s", e)
        return None


async def _cache_get(key: str) -> dict | None:
    redis = await _redis()
    if redis is not None:
        try:
            raw = await redis.get(CACHE_PREFIX + key)
            if raw:
                data = json.loads(raw)
                if isinstance(data, dict) and isinstance(data.get("sections"), dict):
                    return data
        except Exception as e:  # noqa: BLE001
            logger.debug("Edit-status cache read failed: %s", e)
    entry = _PROCESS_CACHE.get(key)
    return entry[1] if entry is not None else None


async def _cache_set(key: str, snap: dict, *, ttl: int | None = None) -> None:
    lifetime = ttl if ttl is not None else int(snap.get("ttl") or settings.GBP_STATUS_CACHE_SECONDS)
    _remember_locally(key, snap)
    redis = await _redis()
    if redis is None:
        return
    try:
        await redis.set(
            CACHE_PREFIX + key, json.dumps(snap, separators=(",", ":")), ex=lifetime
        )
    except Exception as e:  # noqa: BLE001
        logger.debug("Edit-status cache write failed: %s", e)


def _remember_locally(key: str, snap: dict) -> None:
    if len(_PROCESS_CACHE) >= _MAX_PROCESS_ENTRIES:
        cutoff = time.time() - settings.GBP_STATUS_IDLE_SECONDS
        for stale_key, (written, _) in list(_PROCESS_CACHE.items()):
            if written < cutoff:
                _PROCESS_CACHE.pop(stale_key, None)
        if len(_PROCESS_CACHE) >= _MAX_PROCESS_ENTRIES:
            _PROCESS_CACHE.clear()
    _PROCESS_CACHE[key] = (time.time(), snap)


def _lock_for(key: str) -> asyncio.Lock:
    """A per-branch lock bound to the running loop.

    Locks created on a closed loop (a finished test, a reloaded worker)
    raise when reused, so the loop identity is part of the lookup key.
    """
    ident = (id(asyncio.get_running_loop()), key)
    lock = _INFLIGHT_LOCKS.get(ident)
    if lock is None:
        if len(_INFLIGHT_LOCKS) >= _MAX_LOCKS:
            _INFLIGHT_LOCKS.clear()
        lock = asyncio.Lock()
        _INFLIGHT_LOCKS[ident] = lock
    return lock


async def _acquire_remote_lock(redis, key: str) -> bool:
    try:
        got = await redis.set(
            LOCK_PREFIX + key, "1", nx=True, ex=LOCK_TTL_SECONDS
        )
        return bool(got)
    except Exception as e:  # noqa: BLE001 — coordinate best-effort
        logger.debug("Edit-status lock unavailable: %s", e)
        return True


async def _release_remote_lock(redis, key: str) -> None:
    try:
        await redis.delete(LOCK_PREFIX + key)
    except Exception as e:  # noqa: BLE001
        logger.debug("Edit-status lock release failed: %s", e)


async def _wait_for_snapshot(key: str) -> dict | None:
    """Wait briefly for the refresh another worker is already running."""
    deadline = time.monotonic() + LOCK_WAIT_SECONDS
    while time.monotonic() < deadline:
        await asyncio.sleep(LOCK_POLL_INTERVAL_SECONDS)
        snap = await _cache_get(key)
        if snap is not None and snap.get("ok", True):
            return snap
    return None

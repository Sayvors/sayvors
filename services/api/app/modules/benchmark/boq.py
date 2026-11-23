"""Free deep review history from Google's own BOQ panel endpoint.

gosom can only read the handful of reviews Google renders for a signed-out
browser (~5 per place since the 2026 sign-in wall). That is enough to prove a
business exists and to read its rating, but not to say anything about *recent*
review momentum. Google's Local Search panel itself pages the full list through
``GetLocalBoqProxy``; this module reads that same endpoint directly, so review
depth no longer requires a paid provider, a login, or a proxy.

Measured against a 22k-review Riyadh business: 790 unique reviews across 40
pages, ~1.3s per page, no login, no API key. gosom returns 5 for the same place.

Scope rules that keep this cheap and honest:

- **Metadata comes from gosom, reviews come from here.** The BOQ payload has no
  place rating, count, address or photos; inventing them would fill benchmark
  snapshots with nulls. Callers merge these reviews into a gosom result.
- **Newest-first with an early stop.** Reviews are requested sorted newest and
  paging stops as soon as a page crosses the window cutoff, so a normal business
  costs one page and even a very busy one costs a few.
- **The 30-day window is enforced twice**: paging stops at the cutoff *and* the
  result is filtered again, so a provider that ignored the sort cannot leak old
  reviews into "this month".
- **Failures are soft.** A blocked or changed endpoint raises ``BoqError`` and
  the caller keeps whatever gosom returned; review depth is an enhancement, not
  a hard dependency.

The endpoint is undocumented and can change without notice; ``_parse_page``
validates the shape it depends on and raises rather than storing garbage.
"""
from __future__ import annotations

import asyncio
import html
import json
import logging
import math
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)

BOQ_URL = (
    "https://www.google.com/httpservice/web/"
    "PrivateLocalSearchUiDataService/GetLocalBoqProxy"
)

REQUEST_TIMEOUT_SECONDS = 30.0
# Politeness gap between pages. The endpoint is free and unauthenticated; a
# burst of requests is what gets an IP throttled.
PAGE_DELAY_SECONDS = 0.35

# The first page holds ten reviews and every page after it holds twenty.
FIRST_PAGE_SIZE = 10
PAGE_SIZE = 20
# Hard bound: 30 pages is 590 reviews, past any 30-day window this product asks
# for. Without a bound a busy listing pages forever.
MAX_PAGES = 30

# How much review history we keep per place. Mirrors gosom so switching the
# review source never changes what "reviews this month" means.
DEFAULT_REVIEW_WINDOW_DAYS = 30
DEFAULT_MAX_REVIEWS = 500

REVIEW_TEXT_LIMIT = 4000
AUTHOR_LIMIT = 255
PHOTO_URL_LIMIT = 1024

# 2 = newest (1 relevant, 3 highest, 4 lowest). Newest is required for the
# early stop to be sound: once a page crosses the cutoff, every later page is
# older too.
SORT_NEWEST = 2

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
}

# Maps URLs embed the business as !1s0x<hex>:0x<hex>. BOQ keys on that feature
# id; a ChIJ… place id returns HTTP 200 with an empty body, which looks like
# "no reviews" and is why the id format is validated rather than assumed.
_FTID_RE = re.compile(r"!1s(0x[0-9a-fA-F]+:0x[0-9a-fA-F]+)")
# XSSI guard Google prepends to the JSON payload.
_BODY_PREFIX = ")]}'"
_BR_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)


class BoqError(Exception):
    """Review depth could not be read; callers fall back to shallow reviews."""

    def __init__(self, message: str, status_code: int = 502):
        self.status_code = status_code
        super().__init__(message)


def configured() -> bool:
    """Always available: public endpoint, no key, no sidecar, no account."""
    return True


def feature_id(maps_url: str | None) -> str | None:
    """Extract the ``0x…:0x…`` feature id BOQ requires, or ``None``."""
    match = _FTID_RE.search(str(maps_url or ""))
    return match.group(1) if match else None


def _ms_to_rfc3339(value: Any) -> str | None:
    """BOQ publishes epoch milliseconds; the bench stores RFC3339 UTC."""
    if value is None or value == "":
        return None
    try:
        millis = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    if millis <= 0:
        return None
    try:
        return datetime.fromtimestamp(millis / 1000, tz=timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def _clean_text(value: Any) -> str:
    """Strip the panel's ``<br>`` markup and HTML entities, bound the length."""
    text = str(value or "")
    if not text:
        return ""
    return html.unescape(_BR_RE.sub("\n", text)).strip()[:REVIEW_TEXT_LIMIT]


def _at(raw: list, index: int) -> Any:
    return raw[index] if len(raw) > index else None


def _rating(raw: Any) -> int | None:
    try:
        stars = int(raw)
    except (TypeError, ValueError):
        return None
    return stars if 1 <= stars <= 5 else None


def _reply(raw: list) -> tuple[str | None, str | None]:
    """Owner reply text and timestamp.

    The reply's time arrives as either epoch millis or a localized relative
    string ("قبل 6 أيام"). A relative string has no anchor to compute from, so it
    is dropped rather than guessed into a wrong date.
    """
    block = _at(raw, 4)
    if not isinstance(block, list):
        return None, None
    text = _clean_text(_at(block, 2))
    return (text or None), _ms_to_rfc3339(_at(block, 1))


def _review(raw: Any) -> dict[str, Any] | None:
    """Normalize one BOQ review array to the benchmark review shape.

    Field positions are fixed by the panel payload: ``[1]`` rating,
    ``[2][2]`` publish millis, ``[3]`` author ``[name, photo, profile]``,
    ``[4]`` owner reply, ``[5]`` review id, ``[27]`` full text.
    """
    if not isinstance(raw, list) or len(raw) < 6:
        return None
    review_id = str(_at(raw, 5) or "").strip()[:255]
    if not review_id:
        return None

    published = _at(raw, 2)
    publish_ms = _at(published, 2) if isinstance(published, list) else None

    author = _at(raw, 3)
    author_name = author_photo = None
    if isinstance(author, list):
        author_name = str(_at(author, 0) or "").strip()[:AUTHOR_LIMIT] or None
        photo = str(_at(author, 1) or "").strip()
        author_photo = photo[:PHOTO_URL_LIMIT] if photo.startswith("http") else None

    reply_text, reply_time = _reply(raw)
    return {
        "review_id": review_id,
        "rating": _rating(_at(raw, 1)),
        "text": _clean_text(_at(raw, 27)),
        "publish_time": _ms_to_rfc3339(publish_ms),
        "author": author_name,
        "author_photo": author_photo,
        "owner_answer": reply_text,
        "owner_answer_time": reply_time,
    }


def _payload(feature: str, token: str = "", sort: int = SORT_NEWEST) -> list:
    """The panel's request protobuf, as the JSON-array form the endpoint takes."""
    if not token:
        return [
            None,
            [
                None, None, None, None, None, None, None, None, None,
                [None, sort, None, None, None, None, None, None, None,
                 FIRST_PAGE_SIZE, None, [feature]],
            ],
        ]
    return [
        None,
        [
            None, None, None, None, None, None, None, None, None,
            [None, sort, None, None, None, None, None, None, None, None, None,
             [feature], None, None, None, None, None, None, None, token],
        ],
    ]


def _parse_page(body: str) -> tuple[list[Any], str]:
    """Return ``(raw reviews, next token)`` and validate the payload shape.

    Raises instead of returning an empty page when the shape moved: an empty
    list is indistinguishable from "this business has no reviews", and silently
    storing that would wipe a valid review set.
    """
    text = body
    if _BODY_PREFIX in text:
        text = text.split(_BODY_PREFIX, 1)[1]
    text = text.strip()
    if not text:
        raise BoqError("Review depth endpoint returned an empty body")
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise BoqError("Review depth endpoint returned an invalid response") from exc

    node = None
    try:
        node = data[1][10]
    except (IndexError, KeyError, TypeError):
        node = None
    if not isinstance(node, list) or not isinstance(_at(node, 2), list):
        raise BoqError("Review depth response layout changed")
    token = _at(node, 6)
    return node[2], (token if isinstance(token, str) else "")


def _map_reviews(raw_reviews: list[Any], *, cutoff: datetime | None,
                 seen: set[str], out: list[dict[str, Any]]) -> datetime | None:
    """Append new reviews in place; return the oldest publish time seen."""
    oldest: datetime | None = None
    for raw in raw_reviews:
        review = _review(raw)
        if review is None or review["review_id"] in seen:
            continue
        seen.add(review["review_id"])
        published = review.get("publish_time")
        if published:
            moment = datetime.fromisoformat(published)
            if oldest is None or moment < oldest:
                oldest = moment
            # Windows are enforced per review, not just by the paging stop.
            if cutoff is not None and moment < cutoff:
                continue
        out.append(review)
    return oldest


def _pages_for(max_reviews: int) -> int:
    """Pages needed to reach ``max_reviews``, bounded by ``MAX_PAGES``."""
    if max_reviews <= FIRST_PAGE_SIZE:
        return 1
    remaining = max_reviews - FIRST_PAGE_SIZE
    return max(1, min(MAX_PAGES, 1 + math.ceil(remaining / PAGE_SIZE)))


async def fetch_reviews(
    feature: str,
    *,
    max_reviews: int = DEFAULT_MAX_REVIEWS,
    days: int | None = DEFAULT_REVIEW_WINDOW_DAYS,
    client: httpx.AsyncClient | None = None,
) -> list[dict[str, Any]]:
    """Read up to ``max_reviews`` reviews, newest first, stopping at the window.

    Paging stops when the requested depth is reached, when the provider runs out
    of pages, or when a page's oldest review crosses ``days`` — the last one is
    what keeps a 22k-review business from costing 20 requests for a 30-day view.
    """
    key = str(feature or "").strip()
    if not key:
        raise BoqError("Place has no Google feature id", 422)

    try:
        limit = max(1, int(max_reviews))
    except (TypeError, ValueError):
        limit = DEFAULT_MAX_REVIEWS
    cutoff = (
        datetime.now(timezone.utc) - timedelta(days=days)
        if days and days > 0 else None
    )

    reviews: list[dict[str, Any]] = []
    seen: set[str] = set()
    token = ""
    own_client = client is None
    session = client or httpx.AsyncClient(
        timeout=REQUEST_TIMEOUT_SECONDS, follow_redirects=True
    )
    try:
        for page in range(_pages_for(limit)):
            try:
                response = await session.get(
                    BOQ_URL,
                    params={
                        "msc": "gwsrpc",
                        "reqpld": json.dumps(_payload(key, token), separators=(",", ":")),
                    },
                    headers=_HEADERS,
                )
            except httpx.HTTPError as exc:
                raise BoqError("Review depth endpoint is unreachable") from exc

            if response.status_code != 200:
                raise BoqError(
                    f"Review depth endpoint returned HTTP {response.status_code}",
                    503 if response.status_code in (403, 429) else 502,
                )
            raw_reviews, token = _parse_page(response.text)
            oldest = _map_reviews(
                raw_reviews, cutoff=cutoff, seen=seen, out=reviews
            )
            if oldest is not None and cutoff is not None and oldest < cutoff:
                break  # sorted newest: every later page is older still
            if not token or len(reviews) >= limit:
                break
            if page + 1 < _pages_for(limit):
                await asyncio.sleep(PAGE_DELAY_SECONDS)
    finally:
        if own_client:
            await session.aclose()

    reviews.sort(key=lambda row: row.get("publish_time") or "", reverse=True)
    return reviews[:limit]


async def reviews_for_place(
    place_id: str,
    *,
    maps_url: str | None = None,
    max_reviews: int = DEFAULT_MAX_REVIEWS,
    days: int | None = DEFAULT_REVIEW_WINDOW_DAYS,
) -> list[dict[str, Any]]:
    """Reviews for a saved place, using its canonical Maps URL for identity.

    Returns ``[]`` when the stored URL has no feature id: the bench row may
    predate canonical URL capture, and a guess would scrape the wrong business.
    """
    feature = feature_id(maps_url)
    if not feature:
        logger.debug("No BOQ feature id for place %s", place_id)
        return []
    return await fetch_reviews(feature, max_reviews=max_reviews, days=days)

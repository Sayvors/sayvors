"""Google Business Profile (Google Reviews) adapter.

Phase-1 channel integration for Sayvors auto-reply.

Google sends no webhooks for reviews, so new reviews are discovered by
polling `accounts.locations.reviews.list` (see reviews_worker.py) and
replies are posted via `reviews/{id}:replyUpdate`.

Required OAuth scope: https://www.googleapis.com/auth/business.manage
"""
import asyncio
import json
import logging
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import httpx

from ...config import settings

logger = logging.getLogger(__name__)

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GBP_API = "https://mybusinessbusinessinformation.googleapis.com/v1"
GBP_ACCOUNTS_API = "https://mybusinessaccountmanagement.googleapis.com/v1"
# The reviews endpoints live on the older mybusiness API domain:
GBP_REVIEWS_API = "https://mybusiness.googleapis.com/v4"
# My Business Verifications API (locations/{id}:verify, VoiceOfMerchantState)
GBP_VERIFICATIONS_API = "https://mybusinessverifications.googleapis.com/v1"

# Full Google Business Profile access (locations, reviews, replies)
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/business.manage",
    "https://www.googleapis.com/auth/userinfo.profile",
]

TIMEOUT = 15.0

# ── Request resilience ──────────────────────────────────────────────
MAX_REQUEST_ATTEMPTS = 6          # 1 initial attempt + 5 retries
INITIAL_BACKOFF_SECONDS = 1.0     # starting backoff for 429 retries
MAX_BACKOFF_SECONDS = 60.0        # ceiling on computed backoff
MAX_REVIEW_PAGES = 10             # safety cap: 10 x 50 = 500 reviews per poll


def build_auth_url(state: str, redirect_uri: str) -> str:
    """Google OAuth consent URL for Business Profile access."""
    from urllib.parse import urlencode

    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(GOOGLE_SCOPES),
        "access_type": "offline",   # required to get a refresh_token
        "prompt": "consent",        # force refresh_token on repeat connects
        "state": state,
        "include_granted_scopes": "true",
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(params)}"


async def exchange_code(code: str, redirect_uri: str) -> dict:
    """Exchange the OAuth authorization code for access + refresh tokens."""
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        raise GoogleReviewsError(
            "Google OAuth app not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in .env",
            503,
        )
    async with httpx.AsyncClient(timeout=TIMEOUT) as http:
        resp = await http.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
        )
        if resp.status_code != 200:
            raise GoogleReviewsError(
                f"OAuth code exchange failed ({resp.status_code}): {resp.text[:300]}", 401
            )
        return resp.json()  # {access_token, refresh_token?, expires_in, ...}


async def list_accounts(access_token: str) -> list[dict]:
    """List Business Profile accounts the user has access to."""
    async with httpx.AsyncClient(timeout=TIMEOUT) as http:
        resp = await http.get(
            f"{GBP_ACCOUNTS_API}/accounts",
            headers={"Authorization": f"Bearer {access_token}"},
        )
        if resp.status_code != 200:
            raise GoogleReviewsError(
                f"list_accounts failed ({resp.status_code}): {resp.text[:300]}",
                resp.status_code,
            )
        return resp.json().get("accounts", [])


class GoogleReviewsError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        self.status_code = status_code
        super().__init__(message)


@dataclass
class GoogleReview:
    review_id: str          # resource name accounts/{a}/locations/{l}/reviews/{r}
    rating: int             # 1..5
    text: str | None
    reviewer_name: str | None
    reviewer_photo_url: str | None = None
    updated_at: datetime | None = None
    has_reply: bool = False
    # The merchant reply Google already shows. Without this the sync only
    # knew "has_reply=True" and could not show (or preserve) the actual
    # response the business had already written on the listing.
    reply_text: str | None = None
    reply_updated_at: datetime | None = None
    # Photos the reviewer attached. Google returns these as
    # `reviewMediaItems: [{thumbnailUrl, videoUrl, thumbnailLabel}]`.
    media: list[dict] = field(default_factory=list)


_STAR_RATINGS = {
    "ONE": 1, "TWO": 2, "THREE": 3, "FOUR": 4, "FIVE": 5,
}


def _parse_rating(raw) -> int:
    """GBP v4 returns StarRating string enums ("FIVE") — map to 1..5."""
    if isinstance(raw, str):
        return _STAR_RATINGS.get(raw.upper(), 5)
    try:
        return max(1, min(5, int(raw)))
    except (TypeError, ValueError):
        return 5


def location_address(loc: dict) -> str | None:
    """Flatten Google's `storefrontAddress` into the free-text shape the
    benchmark city parser understands."""
    addr = (loc or {}).get("storefrontAddress") or {}
    lines = addr.get("addressLines") or []
    parts = [
        *[str(line) for line in lines if line],
        addr.get("locality"),
        addr.get("administrativeArea"),
        addr.get("postalCode"),
    ]
    text = ", ".join(str(p).strip() for p in parts if p and str(p).strip())
    return text or None


def location_category(loc: dict) -> str | None:
    """Primary Google category display name, when the location has one."""
    cats = (loc or {}).get("categories") or {}
    primary = (cats.get("primaryCategory") or {}).get("displayName")
    return str(primary).strip() if primary else None


def location_phone(loc: dict) -> str | None:
    """Primary phone number on the listing, when the profile has one."""
    phone = ((loc or {}).get("phoneNumbers") or {}).get("primaryPhone")
    return str(phone).strip() if phone else None


def location_website(loc: dict) -> str | None:
    """Website linked to the listing, when the profile has one."""
    site = (loc or {}).get("websiteUri")
    return str(site).strip() if site else None


def location_description(loc: dict) -> str | None:
    """Google's business description, when the profile has one."""
    desc = ((loc or {}).get("profile") or {}).get("description")
    return str(desc).strip() if desc else None


_DAYS = ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY")
_HOURS_DAY_LABEL = {d: d.title() for d in _DAYS}
_MORE_HOURS_LABEL = {
    "ACCESS": "Access", "BREAKFAST": "Breakfast", "BRUNCH": "Brunch",
    "DELIVERY": "Delivery", "DINNER": "Dinner", "DRIVE_THROUGH": "Drive-through",
    "HAPPY_HOUR": "Happy Hour", "KITCHEN": "Kitchen", "LUNCH": "Lunch",
    "ONLINE_SERVICE_HOURS": "Online service", "PICKUP": "Pickup",
    "SENIOR_HOURS": "Senior hours", "TAKEOUT": "Takeout",
}


def _google_time(value: dict | None) -> str:
    """TimeOfDay → "HH:MM". An empty object is Google's midnight."""
    if not value:
        return "00:00"
    hours = int(value.get("hours") or 0)
    minutes = int(value.get("minutes") or 0)
    return f"{hours:02d}:{minutes:02d}"


def location_hours(loc: dict) -> dict:
    """Google regular/special/more hours → the Locations page shape.

    A day with no regular period is closed in Google's model. A 24-hour day
    is open 00:00 and closes at 24:00; the UI carries `all_day` so it can say
    "Open 24 hours" instead of showing 00:00–00:00.
    """
    regular = {
        _HOURS_DAY_LABEL[day]: {"open": "", "close": "", "closed": True}
        for day in _DAYS
    }
    for period in ((loc or {}).get("regularHours") or {}).get("periods") or []:
        day = str(period.get("openDay") or "").upper()
        if day not in _HOURS_DAY_LABEL:
            continue
        opened = _google_time(period.get("openTime"))
        closed = _google_time(period.get("closeTime"))
        all_day = opened == "00:00" and closed == "24:00"
        regular[_HOURS_DAY_LABEL[day]] = {
            "open": "00:00" if all_day else opened,
            "close": "00:00" if all_day else closed,
            "closed": False,
            **({"all_day": True} if all_day else {}),
        }

    special: list[dict] = []
    for period in ((loc or {}).get("specialHours") or {}).get("specialHourPeriods") or []:
        start = period.get("startDate") or {}
        if not start:
            continue
        date = f"{int(start.get('year', 0)):04d}-{int(start.get('month', 0)):02d}-{int(start.get('day', 0)):02d}"
        if period.get("closed"):
            hours = "closed"
        else:
            hours = f"{_google_time(period.get('openTime'))} - {_google_time(period.get('closeTime'))}"
        special.append({"date": date, "hours": hours, "reason": ""})

    more: list[dict] = []
    for entry in ((loc or {}).get("moreHours") or []):
        periods = entry.get("periods") or []
        type_id = str(entry.get("hoursTypeId") or "").upper()
        if not periods or not type_id:
            continue
        period = periods[0]
        more.append({
            "type": _MORE_HOURS_LABEL.get(type_id, type_id.replace("_", " ").title()),
            "open": _google_time(period.get("openTime")),
            "close": _google_time(period.get("closeTime")),
        })

    return {"regular": regular, "special": special, "more": more}


def location_categories(loc: dict) -> dict:
    """Google category display names → the profile's categories shape."""
    cats = (loc or {}).get("categories") or {}
    primary = ((cats.get("primaryCategory") or {}).get("displayName") or "").strip()
    additional = [
        str((c or {}).get("displayName") or "").strip()
        for c in (cats.get("additionalCategories") or [])
        if str((c or {}).get("displayName") or "").strip()
    ]
    return {"primary": primary, "additional": additional}


_ATTRIBUTE_LABEL = {
    "wheelchair_accessible_entrance": "Wheelchair accessible entrance",
    "wheelchair_accessible_parking": "Wheelchair accessible parking",
    "wheelchair_accessible_restroom": "Wheelchair accessible restroom",
    "wheelchair_accessible_seating": "Wheelchair accessible seating",
    "has_wifi": "Free wifi",
    "has_outdoor_seating": "Outdoor seating",
    "has_dine_in": "Dine in",
    "has_takeout": "Takeout",
    "has_delivery": "Delivery",
    "has_drive_through": "Drive through",
    "accepts_credit_cards": "Accepts credit cards",
    "accepts_debit_cards": "Accepts debit cards",
    "accepts_cash_only": "Accepts cash",
    "has_gender_neutral_restrooms": "Gender neutral restroom",
    "is_family_friendly": "Family friendly",
    "is_good_for_children": "Good for children",
    "has_free_parking_lot": "Free parking",
    "has_paid_parking_lot": "Paid parking",
    "has_free_street_parking": "Street parking",
    "allows_dogs": "Pet friendly",
    "has_air_conditioning": "Air conditioning",
    "has_live_music": "Live music",
    "is_sports_bar": "Sports bar",
    "has_online_appointments": "Online appointments",
    "has_on_site_services": "On site services",
}


def location_attributes(attributes: list[dict] | None) -> dict[str, str]:
    """Google merchant attributes → the profile's boolean key/value shape.

    Google returns `name: "attributes/has_wifi"` with `boolValue`; URL-valued
    attributes (text messaging links) are not boolean and are skipped.
    """
    out: dict[str, str] = {}
    for attr in attributes or []:
        raw = str((attr or {}).get("name") or "").split("/")[-1]
        if not raw:
            continue
        values = (attr or {}).get("values") or []
        bool_value = None
        for value in values:
            if "boolValue" in value:
                bool_value = bool(value["boolValue"])
                break
        if bool_value is None:
            continue
        label = _ATTRIBUTE_LABEL.get(raw, raw.replace("_", " ").title())
        out[label] = "yes" if bool_value else "no"
    return out


def location_service_area(loc: dict) -> list[str]:
    """Google serviceArea → the profile's free-text area list."""
    area = (loc or {}).get("serviceArea") or {}
    places = [
        str(p.get("placeName") or p.get("placeId") or "").strip()
        for p in (area.get("places") or [])
        if str(p.get("placeName") or p.get("placeId") or "").strip()
    ]
    region = str(area.get("regionCode") or "").strip()
    if region and region not in places:
        places.append(region)
    return places


def location_service_types(loc: dict) -> list[str]:
    """Google category serviceTypes (the services a merchant declares)."""
    categories = (loc or {}).get("categories") or {}
    groups = [categories.get("primaryCategory")] + list(
        categories.get("additionalCategories") or []
    )
    out: list[str] = []
    for category in groups:
        for service in (category or {}).get("serviceTypes") or []:
            name = str((service or {}).get("displayName") or "").strip()
            if name and name not in out:
                out.append(name)
    return out




def _parse_media(raw) -> list[dict]:
    """Normalise GBP `reviewMediaItems` into the shape we store.

    Each item is `{thumbnailUrl, videoUrl, thumbnailLabel}`. The URLs are
    Google FIFE links, which are short-lived — the sync downloads the bytes
    rather than persisting the URL, so only the label and kind are kept here.
    Items with neither a still nor a video are dropped.
    """
    if not isinstance(raw, (list, tuple)):
        return []
    out: list[dict] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        thumbnail = entry.get("thumbnailUrl")
        video = entry.get("videoUrl")
        if not thumbnail and not video:
            continue
        out.append({
            "thumbnail_url": thumbnail or None,
            "video_url": video or None,
            "label": entry.get("thumbnailLabel") or None,
            "kind": "video" if video else "image",
        })
    return out


def _photo_url(value) -> str | None:
    """Reviewer profile photo from the GBP reviewer object (when present)."""
    if isinstance(value, str) and value.startswith("http"):
        return value
    return None


class GoogleReviewsClient:
    """Thin async client over the Google Business Profile APIs.

    The client is pure HTTP; persistence of refreshed tokens is delegated to an
    optional callback (set via `set_token_persister`) so the worker that owns
    the DB session can decide how/when to write back. This keeps the client
    decoupled from SQLAlchemy.
    """

    # Refresh access tokens a few minutes before the documented expiry to
    # avoid races where a request lands right at the boundary.
    REFRESH_LEEWAY_SECONDS = 60

    def __init__(self, access_token: str, refresh_token: str | None = None):
        self._access_token = access_token
        self._refresh_token = refresh_token
        # When the current access_token expires (UTC). Optional — set when the
        # worker knows the stored token_expires_at from the DB row.
        self._token_expires_at: datetime | None = None
        self._http = httpx.AsyncClient(timeout=TIMEOUT)
        # Persister signature: async def persist(new_access_token, new_expires_at)
        self._persister = None

    async def close(self) -> None:
        await self._http.aclose()

    def set_token_persister(self, persister) -> None:
        """Register an async callback invoked after a successful token refresh.

        `persister(new_access_token: str, new_expires_at: datetime) -> Awaitable[None]`
        It is responsible for encrypting the token and persisting it to the
        Channel row. Not invoked on the initial connect flow.
        """
        self._persister = persister

    def set_known_expiry(self, expires_at: datetime | None) -> None:
        """Inform the client when the current access token is known to expire.

        Used to refresh proactively before the first API call.
        """
        self._token_expires_at = expires_at

    def _is_expiring_soon(self) -> bool:
        if not self._token_expires_at:
            return False
        return datetime.now(timezone.utc) >= (
            self._token_expires_at - timedelta(seconds=self.REFRESH_LEEWAY_SECONDS)
        )

    # ── Auth ─────────────────────────────────────────────

    def _needs_refresh(self) -> bool:
        return (not self._access_token) or self._is_expiring_soon()

    async def refresh_access_token(self) -> str:
        """Exchange the refresh token for a new access token.

        If a persister is registered, the new access token (and computed
        expiry) is written back to the Channel row so the next worker pass
        doesn't repeat the refresh.
        """
        if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
            raise GoogleReviewsError(
                "Google OAuth app not configured (GOOGLE_CLIENT_ID/SECRET)", 503
            )
        if not self._refresh_token:
            raise GoogleReviewsError("No refresh token available", 401)
        resp = await self._http.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": settings.GOOGLE_CLIENT_ID,
                "client_secret": settings.GOOGLE_CLIENT_SECRET,
                "refresh_token": self._refresh_token,
                "grant_type": "refresh_token",
            },
        )
        if resp.status_code != 200:
            raise GoogleReviewsError(f"Token refresh failed: {resp.status_code}", 401)
        data = resp.json()
        self._access_token = data["access_token"]
        # Google returns expires_in (seconds) for access_token grants. If
        # missing (e.g. some flows return only the access token), default to
        # 3600s so we refresh again on the next pass.
        expires_in = int(data.get("expires_in") or 3600)
        self._token_expires_at = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
        if self._persister:
            await self._persister(self._access_token, self._token_expires_at)
        return self._access_token

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self._access_token}"}

    async def _authed_request(self, method: str, url: str, **kwargs) -> httpx.Response:
        """Issue a request, transparently refreshing on 401 and backing off on 429.

        Handles three expiry/limit paths in one place:
          1. Proactive refresh when token_expires_at is set and within leeway.
          2. Reactive refresh when Google returns 401 (token revoked / expired
             server-side despite our local view).
          3. Exponential-backoff retry with jitter when Google returns 429
             (rate limit), honouring the `Retry-After` header when present.

        Persistence of the new token via the registered persister happens on
        successful 401 recovery. All retries are bounded by
        MAX_REQUEST_ATTEMPTS so a single hung channel cannot stall a worker
        pass indefinitely.
        """
        if self._needs_refresh():
            try:
                await self.refresh_access_token()
            except GoogleReviewsError:
                # Fall through; if the first call also fails with 401 we'll
                # try once more below.
                pass

        last_resp: httpx.Response | None = None
        for attempt in range(1, MAX_REQUEST_ATTEMPTS + 1):
            resp = await self._http.request(method, url, headers=self._headers(), **kwargs)

            if resp.status_code not in (401, 429):
                return resp

            last_resp = resp

            if resp.status_code == 401:
                # One-shot retry: refresh and re-issue immediately.
                try:
                    await self.refresh_access_token()
                except GoogleReviewsError as e:
                    raise GoogleReviewsError(
                        f"401 from Google and refresh failed: {e}", 401
                    ) from e
                continue

            # 429 rate limit — back off before retrying.
            if attempt >= MAX_REQUEST_ATTEMPTS:
                break

            wait = self._compute_backoff(resp, attempt)
            logger.warning(
                "429 rate limited on %s %s — retrying in %.1fs (attempt %d/%d)",
                method, url, wait, attempt, MAX_REQUEST_ATTEMPTS,
            )
            await asyncio.sleep(wait)

        # Exhausted all attempts — surface the last response so callers can
        # distinguish a permanent rejection (403/400) from a transient limit.
        if last_resp is not None:
            body = last_resp.text[:300]
            raise GoogleReviewsError(
                f"{last_resp.status_code} from Google after {MAX_REQUEST_ATTEMPTS} attempts: {body}",
                last_resp.status_code,
            )
        raise GoogleReviewsError(
            f"Request failed after {MAX_REQUEST_ATTEMPTS} attempts", 502
        )

    def _compute_backoff(self, resp: httpx.Response, attempt: int) -> float:
        """Seconds to wait before the next 429 retry.

        Honours the `Retry-After` header when present (seconds or HTTP-date).
        Otherwise uses exponential backoff with jitter: base * 2^(attempt-1),
        clamped to MAX_BACKOFF_SECONDS, with ±25% jitter so thundering herds
        don't re-synchronize after a rate-limit window clears.
        """
        retry_after = resp.headers.get("Retry-After")
        if retry_after:
            try:
                return max(0.0, float(retry_after))
            except ValueError:
                pass  # not a delta-seconds value — fall through below
        raw = min(INITIAL_BACKOFF_SECONDS * (2 ** (attempt - 1)), MAX_BACKOFF_SECONDS)
        return raw * (0.75 + 0.5 * random.random())
    # ── Locations ────────────────────────────────────────

    async def list_locations(self, account_id: str) -> list[dict]:
        """List locations for a Business Profile account."""
        resp = await self._authed_request(
            "GET",
            f"{GBP_API}/accounts/{account_id}/locations",
            params={"readMask": "name,title,storefrontAddress,categories,phoneNumbers,websiteUri,profile,regularHours,specialHours,moreHours,serviceArea,metadata"},
        )
        if resp.status_code != 200:
            raise GoogleReviewsError(f"list_locations failed: {resp.status_code}", resp.status_code)
        return resp.json().get("locations", [])

    async def get_location(self, location_id: str) -> dict:
        """One location with its Google Place ID / Maps URL metadata."""
        resp = await self._authed_request(
            "GET",
            f"{GBP_API}/locations/{location_id}",
            params={"readMask": "name,title,storefrontAddress,categories,phoneNumbers,websiteUri,profile,regularHours,specialHours,moreHours,serviceArea,metadata"},
        )
        if resp.status_code != 200:
            raise GoogleReviewsError(
                f"get_location failed ({resp.status_code}): {resp.text[:300]}",
                resp.status_code,
            )
        return resp.json()

    async def get_attributes(self, location_id: str) -> list[dict]:
        """Merchant attributes (wifi, accessibility, …) for one location.

        Attributes live on a separate sub-resource; they are not a valid
        Location readMask field.
        """
        resp = await self._authed_request(
            "GET", f"{GBP_API}/locations/{location_id}/attributes"
        )
        if resp.status_code != 200:
            raise GoogleReviewsError(
                f"get_attributes failed ({resp.status_code}): {resp.text[:300]}",
                resp.status_code,
            )
        data = resp.json()
        return list(data.get("attributes") or []) if isinstance(data, dict) else []

    # ── Local posts (v4) ─────────────────────────────────

    # Per-post performance metrics (reportInsights): views on Google Search
    # and call-to-action button clicks. The only per-post numbers Google
    # exposes.
    LOCAL_POST_METRICS = (
        "LOCAL_POST_VIEWS_SEARCH",
        "LOCAL_POST_ACTIONS_CALL_TO_ACTION",
    )

    async def list_accounts(self) -> list[dict]:
        """Business Profile accounts on the OAuth grant (v1 accountmanagement)."""
        resp = await self._authed_request(
            "GET", f"{GBP_ACCOUNTS_API}/accounts", params={"pageSize": 50})
        if resp.status_code != 200:
            raise GoogleReviewsError(
                f"list_accounts failed ({resp.status_code}): {resp.text[:300]}",
                resp.status_code)
        return resp.json().get("accounts", []) or []

    async def list_local_posts(self, account_id: str, location_id: str) -> list[dict]:
        """All local posts for a location (v4), following pages.

        Returns raw LocalPost dicts — ``name`` (full resource name, the
        reportInsights handle), ``summary``, ``createTime``, ``state``.
        """
        out: list[dict] = []
        page_token: str | None = None
        url = (f"{GBP_REVIEWS_API}/accounts/{account_id}"
               f"/locations/{location_id}/localPosts")
        for _ in range(10):  # 10 x 100 — far past any real feed
            params: dict = {"pageSize": 100}
            if page_token:
                params["pageToken"] = page_token
            resp = await self._authed_request("GET", url, params=params)
            if resp.status_code != 200:
                raise GoogleReviewsError(
                    f"list_local_posts failed ({resp.status_code}): "
                    f"{resp.text[:300]}",
                    resp.status_code)
            data = resp.json()
            out.extend(data.get("localPosts", []) or [])
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        return out

    async def report_local_post_insights(
        self,
        account_id: str,
        location_id: str,
        post_names: list[str],
        start: datetime,
        end: datetime,
    ) -> dict:
        """Per-post views + call-to-action clicks (v4 reportInsights).

        ``post_names`` are full resource names; Google caps one call at 100
        (caller batches). Time range caps at 18 months — pass the widest
        window you want per-post totals over. Returns the raw response
        (``localPostMetrics`` keyed by ``localPostName``).
        """
        url = (f"{GBP_REVIEWS_API}/accounts/{account_id}"
               f"/locations/{location_id}/localPosts:reportInsights")
        body = {
            "localPostNames": post_names[:100],
            "basicRequest": {
                "metricRequests": [
                    {"metric": metric, "options": ["AGGREGATED_TOTAL"]}
                    for metric in self.LOCAL_POST_METRICS
                ],
                "timeRange": {
                    "startTime": start.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                    "endTime": end.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
                },
            },
        }
        resp = await self._authed_request("POST", url, json=body)
        if resp.status_code != 200:
            raise GoogleReviewsError(
                f"report_local_post_insights failed ({resp.status_code}): "
                f"{resp.text[:300]}",
                resp.status_code)
        data = resp.json()
        return data if isinstance(data, dict) else {}

    # ── Reviews ──────────────────────────────────────────

    async def list_reviews(
        self, account_id: str, location_id: str, updated_after: datetime | None = None
    ) -> list[GoogleReview]:
        """Fetch all reviews for a location, following pagination pages.

        Google v4 does not support server-side filtering by updateTime, so we
        page through results (pageSize 50 per request) and filter client-side.
        A safety cap of MAX_REVIEW_PAGES prevents runaway loops on locations
        with very large review histories.
        """
        url = f"{GBP_REVIEWS_API}/accounts/{account_id}/locations/{location_id}/reviews"
        page_token: str | None = None

        all_reviews: list[GoogleReview] = []
        for _ in range(MAX_REVIEW_PAGES):
            params: dict = {"pageSize": 50}
            if page_token:
                params["pageToken"] = page_token

            resp = await self._authed_request("GET", url, params=params)
            if resp.status_code != 200:
                raise GoogleReviewsError(
                    f"list_reviews failed: {resp.status_code}", resp.status_code
                )

            data = resp.json()
            for r in data.get("reviews", []):
                updated = None
                if r.get("updateTime"):
                    try:
                        updated = datetime.fromisoformat(
                            r["updateTime"].replace("Z", "+00:00")
                        )
                    except ValueError:
                        pass
                reply = r.get("reviewReply") or {}
                reply_updated = None
                if reply.get("updateTime"):
                    try:
                        reply_updated = datetime.fromisoformat(
                            reply["updateTime"].replace("Z", "+00:00")
                        )
                    except ValueError:
                        pass
                if updated_after:
                    # A merchant reply added/edited directly in GBP changes
                    # `reviewReply.updateTime`, not necessarily the review's
                    # own updateTime. Let either timestamp make the review due.
                    review_changed = updated is not None and updated > updated_after
                    reply_changed = (
                        reply_updated is not None and reply_updated > updated_after
                    )
                    if not review_changed and not reply_changed:
                        continue
                all_reviews.append(
                    GoogleReview(
                        # GBP v4 uses `starRating` ("FIVE"); the old
                        # `rating` fallback keeps the fake/test shape working.
                        rating=_parse_rating(r.get("starRating") or r.get("rating")),
                        review_id=r.get("name", ""),
                        text=(r.get("comment") or "") or None,
                        reviewer_name=(r.get("reviewer") or {}).get("displayName"),
                        updated_at=updated,
                        has_reply=bool(reply),
                        reply_text=((reply.get("comment") or "").strip() or None),
                        reply_updated_at=reply_updated,
                        reviewer_photo_url=_photo_url((r.get("reviewer") or {}).get("profilePhotoUrl")),
                        media=_parse_media(r.get("reviewMediaItems")),
                    )
                )

            page_token = data.get("nextPageToken")
            if not page_token:
                break

        return all_reviews

    async def reply_to_review(self, review_id: str, comment: str) -> None:
        """Post (or update) the merchant reply on a review."""
        url = f"{GBP_REVIEWS_API}/{review_id}:replyUpdate"
        resp = await self._authed_request("PUT", url, json={"comment": comment})
        if resp.status_code not in (200, 201):
            raise GoogleReviewsError(
                f"replyUpdate failed ({resp.status_code}): {resp.text[:300]}",
                resp.status_code,
            )

    async def delete_reply(self, review_id: str) -> None:
        url = f"{GBP_REVIEWS_API}/{review_id}:deleteReply"
        resp = await self._authed_request("DELETE", url)
        if resp.status_code not in (200, 204):
            raise GoogleReviewsError(
                f"deleteReply failed: {resp.status_code}", resp.status_code
            )

    async def get_review(self, review_resource: str) -> dict:
        """Fetch one review by full resource name
        (``accounts/{a}/locations/{l}/reviews/{r}``).

        Returns the raw payload — it carries ``reviewReply`` when a merchant
        reply is live. Returns {} when the review no longer exists (404).
        """
        resp = await self._authed_request("GET", f"{GBP_REVIEWS_API}/{review_resource}")
        if resp.status_code == 404:
            return {}
        if resp.status_code != 200:
            raise GoogleReviewsError(
                f"get_review failed ({resp.status_code}): {resp.text[:300]}",
                resp.status_code,
            )
        data = resp.json()
        return data if isinstance(data, dict) else {}

    async def confirm_reply_live(self, review_resource: str, attempts: int = 3) -> bool:
        """True only if Google actually shows a reply on the review.

        Never trust the write call alone: a 200 from ``:replyUpdate`` is
        followed by a read, retried a few times to ride out replication
        lag. ``posted`` must mean live — anything else is a lie in the UI.
        """
        for attempt in range(max(1, attempts)):
            payload = await self.get_review(review_resource)
            if payload and payload.get("reviewReply"):
                return True
            if attempt < attempts - 1:
                await asyncio.sleep(2)
        return False

    # ── Questions & Answers (Google Business Profile Q&A v4) ──────────────

    async def list_questions(
        self, account_id: str, location_id: str
    ) -> list[dict]:
        """List all questions for a location.

        Returns raw question dicts (one per page of results). Each dict
        carries ``name`` (full resource name), ``questionText``,
        ``askerProfile`` (displayName, profilePhotoUrl), ``createTime``,
        ``answer`` (if a merchant answer exists), ``upvoteCount``, etc.

        Google pages results; the caller should page through until
        ``nextPageToken`` is absent.
        """
        url = f"{GBP_REVIEWS_API}/accounts/{account_id}/locations/{location_id}/questions"
        out: list[dict] = []
        page_token: str | None = None
        for _ in range(10):  # safety cap; real listings rarely exceed a few pages
            params: dict = {"pageSize": 50}
            if page_token:
                params["pageToken"] = page_token
            resp = await self._authed_request("GET", url, params=params)
            if resp.status_code != 200:
                raise GoogleReviewsError(
                    f"list_questions failed ({resp.status_code}): {resp.text[:300]}",
                    resp.status_code,
                )
            data = resp.json()
            out.extend(data.get("questions", []) or [])
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        return out

    async def answer_question(self, question_id: str, comment: str) -> None:
        """Create or update the merchant answer to a question.

        ``question_id`` is the full resource name
        ``accounts/{a}/locations/{l}/questions/{q}``. Google's v4 method is
        ``questions/{q}/answers:upsert``; there is no ``:answer`` method.
        """
        url = f"{GBP_REVIEWS_API}/{question_id}/answers:upsert"
        resp = await self._authed_request(
            "POST", url, json={"answer": {"text": comment}}
        )
        if resp.status_code not in (200, 201):
            raise GoogleReviewsError(
                f"answerQuestion failed ({resp.status_code}): {resp.text[:300]}",
                resp.status_code,
            )

    async def get_question(self, question_resource: str) -> dict:
        """Fetch one question by full resource name.

        Returns the raw question dict, or {} when the question no longer
        exists (404).
        """
        resp = await self._authed_request("GET", f"{GBP_REVIEWS_API}/{question_resource}")
        if resp.status_code == 404:
            return {}
        if resp.status_code != 200:
            raise GoogleReviewsError(
                f"get_question failed ({resp.status_code}): {resp.text[:300]}",
                resp.status_code,
            )
        data = resp.json()
        return data if isinstance(data, dict) else {}

    # ── Performance (Business Profile Performance API v1) ──────────────────

    PERFORMANCE_API = "https://businessprofileperformance.googleapis.com/v1"

    async def fetch_performance_timeseries(
        self, location_id: str, start_date: datetime, end_date: datetime
    ) -> dict[str, list[tuple]]:
        """Daily performance metrics for a location.

        Returns {metric: [(date, value), ...]} keyed by Google's daily
        metric names. The endpoint is a GET with repeated `dailyMetrics`
        query parameters (not a POST body), and the response nests the
        series under `multiDailyMetricTimeSeries[].dailyMetricTimeSeries[]`.
        """
        url = (
            f"{self.PERFORMANCE_API}/locations/{location_id}"
            f":fetchMultiDailyMetricsTimeSeries"
        )
        params = [
            ("dailyMetrics", metric)
            for metric in (
                "WEBSITE_CLICKS",
                "CALL_CLICKS",
                "BUSINESS_DIRECTION_REQUESTS",
                # The old DIRECTION_REQUESTS / BUSINESS_IMPRESSIONS_* enum
                # names are rejected by the current API.
                "BUSINESS_IMPRESSIONS_DESKTOP_MAPS",
                "BUSINESS_IMPRESSIONS_DESKTOP_SEARCH",
                "BUSINESS_IMPRESSIONS_MOBILE_MAPS",
                "BUSINESS_IMPRESSIONS_MOBILE_SEARCH",
            )
        ] + [
            ("dailyRange.startDate.year", str(start_date.year)),
            ("dailyRange.startDate.month", str(start_date.month)),
            ("dailyRange.startDate.day", str(start_date.day)),
            ("dailyRange.endDate.year", str(end_date.year)),
            ("dailyRange.endDate.month", str(end_date.month)),
            ("dailyRange.endDate.day", str(end_date.day)),
        ]
        resp = await self._authed_request("GET", url, params=params)
        if resp.status_code != 200:
            raise GoogleReviewsError(
                f"fetch_performance_timeseries failed ({resp.status_code}): {resp.text[:300]}",
                resp.status_code,
            )

        out: dict[str, list[tuple]] = {}
        for group in resp.json().get("multiDailyMetricTimeSeries", []):
            for series in group.get("dailyMetricTimeSeries", []):
                metric = series.get("dailyMetric", "")
                dated: list[tuple] = []
                for v in (series.get("timeSeries") or {}).get("datedValues", []):
                    d = v.get("date") or {}
                    raw_value = v.get("value")
                    if raw_value is None:
                        continue
                    try:
                        day = datetime(int(d["year"]), int(d["month"]), int(d["day"]), tzinfo=timezone.utc)
                        dated.append((day.date(), int(raw_value)))
                    except (KeyError, TypeError, ValueError):
                        continue
                if metric and dated:
                    out[metric] = dated
        return out

    async def fetch_keyword_timeseries(
        self, location_id: str, start_date: datetime, end_date: datetime
    ) -> dict[str, list[tuple]]:
        """Monthly search-keyword impressions for a location.

        Google exposes keyword impressions only at monthly granularity via
        `locations.searchkeywords.impressions.monthly` — not as a daily
        metric. Each keyword's aggregate is stored on the first day of its
        month. The fetch covers the trailing six months (not just the daily
        sync window) because completed months are what Google returns and
        the Growth card's 90-day view needs them. Google returns low-volume
        terms as a threshold ("at least 15") rather than an exact count;
        those are omitted instead of being presented as precise numbers.
        """
        def _first_of_month(value):
            if isinstance(value, datetime):
                value = value.date()
            return value.replace(day=1)

        def _next_month(day):
            return (day.replace(day=28) + timedelta(days=4)).replace(day=1)

        url = (
            f"{self.PERFORMANCE_API}/locations/{location_id}"
            f"/searchkeywords/impressions/monthly"
        )
        out: dict[str, list[tuple]] = {}
        last_month = _first_of_month(end_date)
        month = _first_of_month(last_month - timedelta(days=180))
        while month <= last_month:
            base_params = [
                ("monthlyRange.startMonth.year", str(month.year)),
                ("monthlyRange.startMonth.month", str(month.month)),
                ("monthlyRange.endMonth.year", str(month.year)),
                ("monthlyRange.endMonth.month", str(month.month)),
                ("pageSize", "100"),
            ]
            page_token: str | None = None
            for _ in range(10):  # bounded pagination
                params = list(base_params)
                if page_token:
                    params.append(("pageToken", page_token))
                resp = await self._authed_request("GET", url, params=params)
                if resp.status_code != 200:
                    raise GoogleReviewsError(
                        f"fetch_keyword_timeseries failed ({resp.status_code}): {resp.text[:300]}",
                        resp.status_code,
                    )
                data = resp.json()
                for item in data.get("searchKeywordsCounts", []) or []:
                    keyword = (item.get("searchKeyword") or "").strip()
                    insights = item.get("insightsValue") or {}
                    raw_value = insights.get("value")
                    # `threshold` is a lower bound, not an exact count.
                    if not keyword or raw_value is None:
                        continue
                    try:
                        value = int(raw_value)
                    except (TypeError, ValueError):
                        continue
                    out.setdefault(keyword, []).append((month, value))
                page_token = data.get("nextPageToken")
                if not page_token:
                    break
            month = _next_month(month)
        return out

    # ── Verification (My Business Verifications API) ─────

    async def get_voice_of_merchant_state(self, location_id: str) -> dict:
        """Whether Google considers this location verified and in good standing."""
        resp = await self._authed_request(
            "GET",
            f"{GBP_VERIFICATIONS_API}/locations/{location_id}/VoiceOfMerchantState",
        )
        if resp.status_code != 200:
            raise GoogleReviewsError(
                f"VoiceOfMerchantState failed ({resp.status_code}): {resp.text[:300]}",
                resp.status_code,
            )
        return resp.json() or {}

    async def fetch_verification_options(
        self, location_id: str, language_code: str = "en"
    ) -> list[dict]:
        """Eligible verification methods and the contact data Google will use.

        Google returns an empty object when the location is already verified
        or when no method is currently eligible; both are honest empty states,
        not errors.
        """
        resp = await self._authed_request(
            "POST",
            f"{GBP_VERIFICATIONS_API}/locations/{location_id}:fetchVerificationOptions",
            json={"languageCode": language_code or "en"},
        )
        if resp.status_code != 200:
            raise GoogleReviewsError(
                f"fetchVerificationOptions failed ({resp.status_code}): {resp.text[:300]}",
                resp.status_code,
            )
        data = resp.json() or {}
        return data.get("options", []) or []

    async def list_verifications(self, location_id: str) -> list[dict]:
        """Every verification request Google has recorded for the location."""
        out: list[dict] = []
        page_token: str | None = None
        for _ in range(10):  # bounded pagination
            params: dict = {"pageSize": 100}
            if page_token:
                params["pageToken"] = page_token
            resp = await self._authed_request(
                "GET",
                f"{GBP_VERIFICATIONS_API}/locations/{location_id}/verifications",
                params=params,
            )
            if resp.status_code != 200:
                raise GoogleReviewsError(
                    f"list verifications failed ({resp.status_code}): {resp.text[:300]}",
                    resp.status_code,
                )
            data = resp.json() or {}
            out.extend(data.get("verifications", []) or [])
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        return out

    async def verify_location(
        self,
        location_id: str,
        *,
        method: str,
        language_code: str = "en",
        phone_number: str | None = None,
        email_address: str | None = None,
        mailer_contact: str | None = None,
        trusted_partner_token: str | None = None,
    ) -> dict:
        """Start a verification request and return Google's verification."""
        body: dict = {"method": method, "languageCode": language_code or "en"}
        if phone_number:
            body["phoneNumber"] = phone_number
        if email_address:
            body["emailAddress"] = email_address
        if mailer_contact:
            body["mailerContact"] = mailer_contact
        if trusted_partner_token:
            body["token"] = {"tokenString": trusted_partner_token}
        resp = await self._authed_request(
            "POST",
            f"{GBP_VERIFICATIONS_API}/locations/{location_id}:verify",
            json=body,
        )
        if resp.status_code != 200:
            raise GoogleReviewsError(
                f"verify location failed ({resp.status_code}): {resp.text[:300]}",
                resp.status_code,
            )
        return (resp.json() or {}).get("verification") or {}

    async def complete_verification(self, name: str, pin: str) -> dict:
        """Complete a PENDING verification with the PIN the merchant received."""
        resp = await self._authed_request(
            "POST",
            f"{GBP_VERIFICATIONS_API}/{name}:complete",
            json={"pin": pin},
        )
        if resp.status_code != 200:
            raise GoogleReviewsError(
                f"complete verification failed ({resp.status_code}): {resp.text[:300]}",
                resp.status_code,
            )
        return (resp.json() or {}).get("verification") or {}


def parse_review_resource(review_id: str) -> tuple[str, str] | None:
    """Split 'accounts/{a}/locations/{l}/reviews/{r}' into (account, location)."""
    parts = review_id.split("/")
    if len(parts) == 6 and parts[0] == "accounts" and parts[2] == "locations":
        return parts[1], parts[3]
    return None

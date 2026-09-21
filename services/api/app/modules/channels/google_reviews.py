"""Google Business Profile (Google Reviews) adapter.

Phase-1 channel integration for Sayvors auto-reply.

Google sends no webhooks for reviews, so new reviews are discovered by
polling `accounts.locations.reviews.list` (see reviews_worker.py) and
replies are posted via `reviews/{id}:replyUpdate`.

Required OAuth scope: https://www.googleapis.com/auth/business.manage
"""
import asyncio
import logging
from dataclasses import dataclass
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

# Full Google Business Profile access (locations, reviews, replies)
GOOGLE_SCOPES = [
    "https://www.googleapis.com/auth/business.manage",
    "https://www.googleapis.com/auth/userinfo.profile",
]

TIMEOUT = 15.0


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
    updated_at: datetime | None
    has_reply: bool


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
        """Issue a request, transparently refreshing on 401 and retrying once.

        Handles three expiry paths in one place:
          1. Proactive refresh when token_expires_at is set and within leeway.
          2. Reactive refresh when Google returns 401 (token revoked / expired
             server-side despite our local view).
          3. Persistence of the new token via the registered persister.
        """
        if self._needs_refresh():
            try:
                await self.refresh_access_token()
            except GoogleReviewsError:
                # Fall through; if the first call also fails with 401 we'll
                # try once more below.
                pass

        resp = await self._http.request(method, url, headers=self._headers(), **kwargs)
        if resp.status_code != 401:
            return resp

        # One-shot retry: refresh and re-issue.
        try:
            await self.refresh_access_token()
        except GoogleReviewsError as e:
            raise GoogleReviewsError(
                f"401 from Google and refresh failed: {e}", 401
            ) from e

        return await self._http.request(method, url, headers=self._headers(), **kwargs)
    # ── Locations ────────────────────────────────────────

    async def list_locations(self, account_id: str) -> list[dict]:
        """List locations for a Business Profile account."""
        resp = await self._authed_request(
            "GET",
            f"{GBP_API}/accounts/{account_id}/locations",
            params={"readMask": "name,title,storefrontAddress"},
        )
        if resp.status_code != 200:
            raise GoogleReviewsError(f"list_locations failed: {resp.status_code}", resp.status_code)
        return resp.json().get("locations", [])

    # ── Reviews ──────────────────────────────────────────

    async def list_reviews(
        self, account_id: str, location_id: str, updated_after: datetime | None = None
    ) -> list[GoogleReview]:
        """Fetch reviews for a location, newest-updated first.

        Google v4 does not support server-side filtering by updateTime, so we
        fetch a bounded page (pageSize) and filter client-side.
        """
        url = f"{GBP_REVIEWS_API}/accounts/{account_id}/locations/{location_id}/reviews"
        params: dict = {"pageSize": 50}
        resp = await self._authed_request("GET", url, params=params)
        if resp.status_code != 200:
            raise GoogleReviewsError(
                f"list_reviews failed: {resp.status_code}", resp.status_code
            )

        reviews: list[GoogleReview] = []
        for r in resp.json().get("reviews", []):
            updated = None
            if r.get("updateTime"):
                try:
                    updated = datetime.fromisoformat(
                        r["updateTime"].replace("Z", "+00:00")
                    )
                except ValueError:
                    pass
            if updated_after and updated and updated <= updated_after:
                continue
            reviews.append(
                GoogleReview(
                    review_id=r.get("name", ""),
                    rating=_parse_rating(r.get("rating", 5)),
                    text=(r.get("comment") or "") or None,
                    reviewer_name=(r.get("reviewer") or {}).get("displayName"),
                    updated_at=updated,
                    has_reply=bool(r.get("reviewReply")),
                )
            )
        return reviews

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

    # ── Performance (Business Profile Performance API v1) ──────────────────

    PERFORMANCE_API = "https://businessprofileperformance.googleapis.com/v1"

    async def fetch_performance_timeseries(
        self, location_id: str, start_date: datetime, end_date: datetime
    ) -> dict[str, list[tuple]]:
        """Daily performance metrics for a location.

        Returns {metric_type: [(date, value), ...]} for the supported
        DailyMetricType values (customer actions + impressions). The map is
        keyed by the raw Google metric names, e.g. "WEBSITE_CLICKS".
        """
        def _d(d: datetime) -> dict:
            return {"year": d.year, "month": d.month, "day": d.day}

        url = (
            f"{self.PERFORMANCE_API}/locations/{location_id}"
            f":fetchMultiDailyMetricsTimeSeries"
        )
        body = {
            "dailyMetrics": [
                "WEBSITE_CLICKS",
                "CALL_CLICKS",
                "DIRECTION_REQUESTS",
                "BUSINESS_IMPRESSIONS_DESKTOP",
                "BUSINESS_IMPRESSIONS_MOBILE",
            ],
            "dailyRange": {"startDate": _d(start_date), "endDate": _d(end_date)},
        }
        resp = await self._authed_request("POST", url, json=body)
        if resp.status_code != 200:
            raise GoogleReviewsError(
                f"fetch_performance_timeseries failed ({resp.status_code}): {resp.text[:300]}",
                resp.status_code,
            )

        out: dict[str, list[tuple]] = {}
        for series in resp.json().get("multiDailyMetricTimeSeries", []):
            metric = series.get("dailyMetricType", "")
            dated: list[tuple] = []
            for v in (series.get("timeSeries") or {}).get("datedValues", []):
                d = v.get("date") or {}
                raw_value = v.get("value")
                if not raw_value:
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
        """Daily search-keyword impressions for a location.

        Returns {keyword: [(date, impressions), ...]}. Only the native
        Google path can produce this — Localith has no keyword endpoint,
        so Localith-only tenants get an honest empty state, never fake rows.
        """
        def _d(d: datetime) -> dict:
            return {"year": d.year, "month": d.month, "day": d.day}

        url = (
            f"{self.PERFORMANCE_API}/locations/{location_id}"
            f":fetchMultiDailyMetricsTimeSeries"
        )
        body = {
            "dailyMetrics": ["SEARCH_KEYWORD_IMPRESSIONS"],
            "dailyRange": {"startDate": _d(start_date), "endDate": _d(end_date)},
        }
        resp = await self._authed_request("POST", url, json=body)
        if resp.status_code != 200:
            raise GoogleReviewsError(
                f"fetch_keyword_timeseries failed ({resp.status_code}): {resp.text[:300]}",
                resp.status_code,
            )

        out: dict[str, list[tuple]] = {}
        for series in resp.json().get("multiDailyMetricTimeSeries", []):
            for kw_block in series.get("searchKeywordImpressions", []):
                keyword = (kw_block.get("searchKeyword") or "").strip()
                if not keyword:
                    continue
                dated: list[tuple] = []
                inner = (kw_block.get("dailyMetricTimeSeries") or {}).get(
                    "timeSeries", {})
                for v in inner.get("datedValues", []):
                    d = v.get("date") or {}
                    raw_value = v.get("value")
                    if not raw_value:
                        continue
                    try:
                        day = datetime(int(d["year"]), int(d["month"]), int(d["day"]),
                                       tzinfo=timezone.utc)
                        dated.append((day.date(), int(raw_value)))
                    except (KeyError, TypeError, ValueError):
                        continue
                if dated:
                    out.setdefault(keyword, []).extend(dated)
        return out


def parse_review_resource(review_id: str) -> tuple[str, str] | None:
    """Split 'accounts/{a}/locations/{l}/reviews/{r}' into (account, location)."""
    parts = review_id.split("/")
    if len(parts) == 6 and parts[0] == "accounts" and parts[2] == "locations":
        return parts[1], parts[3]
    return None

"""Instagram adapter (Login for Business with its own configuration).

The connect dialog uses META_INSTAGRAM_CONFIG_ID — independent from the
Facebook configuration. Token exchange reuses the Facebook Login stack;
IG business accounts are discovered per Facebook Page and API eligibility
(professional + public) is validated at connect time.
"""
import logging
from urllib.parse import urlencode

from .....config import settings
from .base import DiscoveredAsset, MetaAPIError, MetaProviderAdapter

logger = logging.getLogger(__name__)


class InstagramAdapter(MetaProviderAdapter):
    provider = "instagram"

    def build_auth_entry(self, state: str) -> dict:
        # Instagram connects through its own Login for Business
        # configuration — never the Facebook one. Dialog shape is
        # identical; only config_id differs.
        if not settings.META_APP_ID or not settings.META_INSTAGRAM_CONFIG_ID:
            raise MetaAPIError(
                "Instagram Login not configured. Set META_APP_ID / "
                "META_INSTAGRAM_CONFIG_ID in .env",
                503,
            )
        from .facebook import FB_DIALOG_URL

        params = {
            "client_id": settings.META_APP_ID,
            "redirect_uri": settings.META_OAUTH_REDIRECT_URI,
            "config_id": settings.META_INSTAGRAM_CONFIG_ID,
            "response_type": "code",
            "override_default_response_type": "true",
            "state": state,
        }
        return {
            "auth_url": f"{FB_DIALOG_URL}?{urlencode(params)}",
            "state": state,
            "note": "Connect Instagram, then use 'Discover from my Pages'.",
        }

    async def exchange_code(self, code: str, redirect_uri: str | None = None) -> dict:
        from .facebook import FacebookAdapter

        return await FacebookAdapter().exchange_code(code, redirect_uri)

    async def discover_assets(
        self, credentials: dict, pages: list[dict] | None = None
    ) -> list[DiscoveredAsset]:
        """Find IG business accounts linked to the given Pages.

        `pages`: [{external_asset_id, page_access_token, name}].
        """
        out: list[DiscoveredAsset] = []
        for page in pages or []:
            page_id = page.get("external_asset_id", "")
            page_token = page.get("page_access_token", "")
            if not page_id or not page_token:
                continue
            resp = await self._graph(
                "GET",
                f"/{page_id}",
                page_token,
                params={"fields": "instagram_business_account{id,username,profile_picture_url}"},
            )
            ig = (resp.json().get("instagram_business_account") or {})
            if ig.get("id"):
                out.append(
                    DiscoveredAsset(
                        asset_type="ig_account",
                        external_asset_id=ig["id"],
                        parent_external_id=page_id,
                        username=ig.get("username"),
                        name=ig.get("username"),
                        extra={"page_name": page.get("name")},
                    )
                )
        logger.info("Instagram asset discovery: %d accounts", len(out))
        return out

    async def check_eligibility(self, ig_id: str, token: str) -> tuple[bool, str]:
        """Validate the IG account can use the API (professional + reachable).

        Note: do NOT ask for `account_type` here. It is not a readable field on
        the IG User node in current Graph versions — requesting it returns
        "(#100) Tried accessing nonexisting field (account_type)" and failed
        the whole call, which marked every discovered account "ineligible".
        Meta already refuses API access for personal accounts, so a successful
        read IS the eligibility signal.
        """
        try:
            resp = await self._graph(
                "GET",
                f"/{ig_id}",
                token,
                params={"fields": "id,username,media_count"},
            )
        except MetaAPIError as e:
            return False, f"graph error {e.status_code}"
        data = resp.json() or {}
        if not data.get("username"):
            return False, "account not readable — it may be private or personal"
        return True, f"eligible (@{data['username']})"

    async def validate_connection(self, connection, credentials: dict) -> tuple[bool, str]:
        token = credentials.get("access_token", "")
        if not token:
            return False, "missing token"
        try:
            resp = await self._graph("GET", "/me/accounts", token, params={"limit": 1})
            return (True, "ok") if resp.status_code == 200 else (False, "invalid token")
        except MetaAPIError as e:
            return False, f"graph error {e.status_code}"

    # ── Messaging ────────────────────────────────────────────
    # IG DMs ride the PARENT FACEBOOK PAGE's token (page-linked
    # messaging): POST /{page-id}/messages with the customer's IGSID as
    # the recipient. No messaging_product field — that is what makes
    # Meta route it to Instagram instead of Messenger.

    IG_TEXT_MAX_BYTES = 1000  # Meta: UTF-8 text, 1000 bytes or fewer.

    async def send_text_message(
        self, page_id: str, page_token: str, igsid: str, text: str
    ) -> str:
        # Byte-safe truncation: a str slice can still blow past Meta's
        # byte cap for Arabic/CJK-heavy replies, so truncate the encoding.
        body = text.encode("utf-8")[: self.IG_TEXT_MAX_BYTES].decode(
            "utf-8", errors="ignore"
        )
        resp = await self._graph(
            "POST", f"/{page_id}/messages", page_token,
            json={"recipient": {"id": igsid}, "message": {"text": body}},
        )
        return resp.json().get("message_id", "")

    async def send_typing_indicator(
        self, page_id: str, page_token: str, igsid: str
    ) -> bool:
        try:
            await self._graph(
                "POST", f"/{page_id}/messages", page_token,
                json={"recipient": {"id": igsid}, "sender_action": "typing_on"},
            )
            return True
        except MetaAPIError:
            return False

    async def get_contact_profile(self, page_token: str, igsid: str) -> dict:
        """Best-effort name/username/avatar for the inbox — {} on any failure."""
        try:
            resp = await self._graph(
                "GET", f"/{igsid}", page_token,
                params={"fields": "name,username,profile_pic"},
            )
            return resp.json() or {}
        except MetaAPIError:
            return {}

    # ── Audience ─────────────────────────────────────────────
    # Meta does NOT expose follower/following lists ("Read anyone's
    # follower/following lists - not exposed" in the API reference), so there is
    # no follower roster to build. What IS available, and what a "followers"
    # request is usually actually after, is the people who engaged: commenters
    # on your own posts, plus follower DEMOGRAPHICS in aggregate.

    COMMENTER_FIELDS = (
        "id,permalink,caption,"
        "comments{id,text,timestamp,username,like_count,from{id}}"
    )

    async def get_recent_commenters(
        self, ig_id: str, token: str, media_limit: int = 10
    ) -> list[dict]:
        """People who commented on recent posts, newest first.

        Needs instagram_manage_comments. If that scope is missing the read
        fails; callers treat an empty list as "no data" rather than an error so
        the rest of the audience tab still works.
        """
        try:
            resp = await self._graph(
                "GET",
                f"/{ig_id}/media",
                token,
                params={
                    "fields": self.COMMENTER_FIELDS,
                    "limit": max(1, min(media_limit, 25)),
                },
            )
        except MetaAPIError:
            logger.info("Instagram comment read unavailable (scope?)")
            return []
        media = (resp.json() or {}).get("data") or []
        out: list[dict] = []
        for item in media:
            permalink = item.get("permalink")
            for c in item.get("comments", {}).get("data", []) or []:
                username = c.get("username")
                out.append(
                    {
                        "source": "comment",
                        "ig_id": (c.get("from") or {}).get("id"),
                        "username": username,
                        "name": username,
                        "text": c.get("text"),
                        "like_count": int(c.get("like_count") or 0),
                        "occurred_at": c.get("timestamp"),
                        "media_id": item.get("id"),
                        "permalink": permalink,
                        # The profile link Meta itself exposes for a person.
                        "profile_url": f"https://instagram.com/{username}" if username else None,
                    }
                )
        out.sort(key=lambda r: r.get("occurred_at") or "", reverse=True)
        return out

    POST_FIELDS = (
        "id,caption,media_type,media_product_type,media_url,thumbnail_url,permalink,timestamp,"
        "like_count,comments_count,"
        "children{id,media_type,media_url,thumbnail_url},"
        "comments{id,text,timestamp,username,like_count,from{id},hidden,"
        "replies{id,text,timestamp,username,like_count,hidden}}"
    )

    async def get_recent_posts(
        self, ig_id: str, token: str, limit: int = 12, comment_limit: int = 20
    ) -> list[dict]:
        """Your own recent posts, each with its most recent comments.

        This is where a "who is interacting with me" list actually comes from:
        commenters carry usernames, so every one of them gets a real profile
        link. Returns [] when the account has no posts yet - an empty feed is
        the truthful answer, not an error.
        """
        try:
            resp = await self._graph(
                "GET",
                f"/{ig_id}/media",
                token,
                params={"fields": self.POST_FIELDS, "limit": max(1, min(limit, 50))},
            )
        except MetaAPIError as e:
            # No posts, or a sub-field was refused (comments scope, children,
            # media_product_type): fall back to the plain post set so the feed
            # still renders.
            logger.info("Instagram post read degraded: %s", e)
            try:
                resp = await self._graph(
                    "GET",
                    f"/{ig_id}/media",
                    token,
                    params={
                        "fields": "id,caption,media_type,media_url,thumbnail_url,permalink,timestamp,like_count,comments_count",
                        "limit": max(1, min(limit, 50)),
                    },
                )
            except MetaAPIError:
                return []
        media = (resp.json() or {}).get("data") or []
        posts: list[dict] = []
        for item in media:
            comments = []
            for c in (item.get("comments", {}) or {}).get("data", []) or []:
                username = c.get("username")
                replies = [
                    {
                        "id": r.get("id"),
                        "text": r.get("text"),
                        "username": r.get("username"),
                        "timestamp": r.get("timestamp"),
                        "like_count": int(r.get("like_count") or 0),
                        "hidden": bool(r.get("hidden")),
                    }
                    for r in (c.get("replies", {}) or {}).get("data", []) or []
                ]
                comments.append(
                    {
                        "id": c.get("id"),
                        "text": c.get("text"),
                        "username": username,
                        "name": username,
                        "ig_id": (c.get("from") or {}).get("id"),
                        "like_count": int(c.get("like_count") or 0),
                        "timestamp": c.get("timestamp"),
                        "hidden": bool(c.get("hidden")),
                        "media_id": item.get("id"),
                        "profile_url": f"https://instagram.com/{username}" if username else None,
                        "replies": replies,
                    }
                )
            posts.append(
                {
                    "id": item.get("id"),
                    "caption": item.get("caption"),
                    "media_type": item.get("media_type"),
                    "media_product_type": item.get("media_product_type"),
                    "media_url": item.get("media_url"),
                    "thumbnail_url": item.get("thumbnail_url"),
                    "permalink": item.get("permalink"),
                    "timestamp": item.get("timestamp"),
                    "like_count": int(item.get("like_count") or 0),
                    "comments_count": int(item.get("comments_count") or 0),
                    "children": [
                        {
                            "id": ch.get("id"),
                            "media_type": ch.get("media_type"),
                            "media_url": ch.get("media_url"),
                            "thumbnail_url": ch.get("thumbnail_url"),
                        }
                        for ch in (item.get("children", {}) or {}).get("data", []) or []
                    ],
                    "comments": comments[:comment_limit],
                }
            )
        return posts

    # ── Stories ──────────────────────────────────────────────
    # GET /{ig-user-id}/stories is the ONLY stories surface in the API, and
    # it covers the account's own live stories (they expire after 24h).
    # Other accounts' stories are private; the viewer list ("seen by") is
    # exposed to no one, anywhere.

    STORY_FIELDS = "id,media_type,media_url,timestamp"

    async def get_stories(self, ig_id: str, token: str) -> list[dict]:
        """The account's live stories, newest first. [] when none are up."""
        try:
            resp = await self._graph(
                "GET", f"/{ig_id}/stories", token,
                params={"fields": self.STORY_FIELDS},
            )
        except MetaAPIError:
            logger.info("Instagram stories read unavailable (none live, or scope refused)")
            return []
        return [
            {
                "id": s.get("id"),
                "media_type": s.get("media_type"),
                "media_url": s.get("media_url"),
                "timestamp": s.get("timestamp"),
            }
            for s in (resp.json() or {}).get("data", []) or []
        ]

    # Per-post insights. Metric names differ by media type and Graph rejects
    # the WHOLE call when one metric is wrong for the type, so each type gets
    # its own conservative set. REELS is the only surface that exposes shares.
    _INSIGHT_METRICS = {
        "IMAGE": "impressions,reach,saved",
        "CAROUSEL_ALBUM": "impressions,reach",
        "VIDEO": "impressions,reach,video_views",
        "REELS": "plays,reach,saved,shares",
    }

    async def get_media_insights(
        self, media_id: str, token: str, media_type: str | None
    ) -> dict:
        """Reach/saves/shares for one post. {} when refused or unsupported.

        Metrics are an owner-only, insights-scoped read; raising here would
        make every modal open brittle, so any failure degrades to {} and the
        UI simply hides the line.
        """
        metrics = self._INSIGHT_METRICS.get(
            (media_type or "").upper()
        ) or self._INSIGHT_METRICS["IMAGE"]
        try:
            resp = await self._graph(
                "GET", f"/{media_id}/insights", token,
                params={"metric": metrics},
            )
        except MetaAPIError:
            return {}
        out: dict = {}
        for row in (resp.json() or {}).get("data", []) or []:
            name = row.get("name", "")
            value = ((row.get("values") or [{}])[0].get("value"))
            if value is None:
                continue
            out[name] = int(value)
        return out

    async def get_follower_demographics(self, ig_id: str, token: str) -> dict:
        """Aggregate follower demographics (age, gender, top cities/countries).

        Requires instagram_manage_insights AND 100+ followers. Raises
        MetaAPIError when either is missing so the UI can say why.
        """
        resp = await self._graph(
            "GET",
            f"/{ig_id}",
            token,
            params={"fields": "insights.metric(follower_demographics)"},
        )
        insights = (resp.json() or {}).get("insights", {}).get("data", []) or []
        buckets: dict[str, list[dict]] = {}
        for row in insights:
            for entry in row.get("values", []) or []:
                for b in entry.get("breakdowns", []) or []:
                    # Real payloads put the dimension on the VALUE
                    # ("age", "gender", ...). Fall back to the breakdown's
                    # dim_keys, then to the row metric, so a shape change
                    # never silently drops the data.
                    dim_keys = b.get("dim_keys") or []
                    metric = (
                        entry.get("metric")
                        or (dim_keys[0] if dim_keys else "")
                        or row.get("metric")
                        or ""
                    )
                    for dim in b.get("dimension_values", []) or []:
                        buckets.setdefault(metric, []).append(
                            {"label": dim.get("display_value") or dim.get("value"), "value": dim.get("value", 0)}
                        )
        return {
            "age": buckets.get("age", []),
            "gender": buckets.get("gender", []),
            "cities": buckets.get("cities", []),
            "countries": buckets.get("countries", []),
        }
    # Meta's IG User reference states it plainly: "Updating: This operation is
    # not supported." name, biography, website, username and the avatar are all
    # readable and none of them are writable over the Graph API, so there is
    # deliberately no set_business_profile counterpart to WhatsApp's. Do not
    # add one: a save button here would 400 from Graph and lose the tenant's
    # edits. capabilities.py agrees - Instagram has read_profile, never
    # manage_profile.

    # Fields documented on the IG User node. `account_type` is deliberately
    # absent: Meta rejects the whole request with "(#100) Tried accessing
    # nonexisting field (account_type)", which is how this page first shipped
    # broken. Keep this list to fields the reference actually lists.
    PROFILE_FIELDS = (
        "id,username,name,biography,website,profile_picture_url,"
        "followers_count,follows_count,media_count"
    )

    # If Meta ever rejects one of the optional fields again, degrade to this
    # set rather than showing an empty profile.
    MINIMAL_FIELDS = "id,username,name"

    async def get_business_profile(self, ig_id: str, token: str) -> dict:
        """Live IG business profile. Read-only by Meta's design.

        Field availability shifts with Graph version and app permissions, so a
        rejected optional field falls back to the minimal read instead of
        failing the whole page.
        """
        try:
            resp = await self._graph(
                "GET", f"/{ig_id}", token, params={"fields": self.PROFILE_FIELDS}
            )
            data = resp.json() or {}
        except MetaAPIError:
            resp = await self._graph(
                "GET", f"/{ig_id}", token, params={"fields": self.MINIMAL_FIELDS}
            )
            data = resp.json() or {}
        # Normalise the counters: Meta omits them rather than sending null.
        for key in ("followers_count", "follows_count", "media_count"):
            if data.get(key) is None:
                data[key] = 0
        return data

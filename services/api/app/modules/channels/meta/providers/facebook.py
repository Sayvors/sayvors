"""Facebook Pages adapter (Facebook Login for Business).

Dialog is built from the dashboard configuration id (no `scope` param).
Business system-user token -> /me/accounts -> tenant selects Page(s) ->
per-Page tokens persisted on the asset rows.
"""
import logging
from urllib.parse import urlencode

from .....config import settings
from .base import DiscoveredAsset, MetaAPIError, MetaProviderAdapter, graph_base

logger = logging.getLogger(__name__)

FB_DIALOG_URL = "https://www.facebook.com/v26.0/dialog/oauth"


class FacebookAdapter(MetaProviderAdapter):
    provider = "facebook"

    def build_auth_entry(self, state: str) -> dict:
        if not settings.META_APP_ID or not settings.META_FACEBOOK_CONFIG_ID:
            raise MetaAPIError(
                "Facebook Login not configured. Set META_APP_ID / "
                "META_FACEBOOK_CONFIG_ID in .env",
                503,
            )
        params = {
            "client_id": settings.META_APP_ID,
            "redirect_uri": settings.META_OAUTH_REDIRECT_URI,
            "config_id": settings.META_FACEBOOK_CONFIG_ID,
            "response_type": "code",
            "override_default_response_type": "true",
            "state": state,
        }
        return {"auth_url": f"{FB_DIALOG_URL}?{urlencode(params)}", "state": state}

    async def exchange_code(self, code: str, redirect_uri: str | None = None) -> dict:
        if not settings.META_APP_ID or not settings.META_APP_SECRET:
            raise MetaAPIError("Meta app not configured (META_APP_ID/SECRET)", 503)
        resp = await self._http.get(
            f"{graph_base()}/oauth/access_token",
            params={
                "client_id": settings.META_APP_ID,
                "client_secret": settings.META_APP_SECRET,
                "redirect_uri": redirect_uri or settings.META_OAUTH_REDIRECT_URI,
                "code": code,
            },
        )
        if resp.status_code != 200:
            raise MetaAPIError(
                f"Facebook code exchange failed ({resp.status_code}): "
                f"{resp.text[:300]}",
                401,
            )
        return resp.json()

    async def discover_assets(self, credentials: dict) -> list[DiscoveredAsset]:
        token = credentials.get("access_token", "")
        # access_token + tasks are required: the page token powers all
        # page-level API calls, tasks tells what it may do. Never log it.
        resp = await self._graph(
            "GET", "/me/accounts", token,
            params={"fields": "id,name,link,access_token,tasks"},
        )
        try:
            data = resp.json().get("data", [])
        except Exception:
            data = []
        logger.info(
            "Facebook /me/accounts: status=%s pages=%d token_present=%s",
            resp.status_code, len(data), bool(token),
        )
        out = [
            DiscoveredAsset(
                asset_type="page",
                external_asset_id=p.get("id", ""),
                name=p.get("name"),
                extra={
                    "link": p.get("link"),
                    # Page-scoped token for page-level API calls.
                    "page_access_token": p.get("access_token", ""),
                },
            )
            for p in data
            if p.get("id")
        ]
        logger.info("Facebook asset discovery: %d pages", len(out))
        return out

    async def subscribe_page(self, page_id: str, page_token: str, fields: list[str] | None = None) -> None:
        await self._graph(
            "POST",
            f"/{page_id}/subscribed_apps",
            page_token,
            json={"subscribed_fields": fields or ["feed"]},
        )

    async def validate_connection(self, connection, credentials: dict) -> tuple[bool, str]:
        token = credentials.get("access_token", "")
        if not token:
            return False, "missing token"
        try:
            resp = await self._graph("GET", "/me", token, params={"fields": "id,name"})
            data = resp.json()
            return (True, f"ok ({data.get('name', data.get('id', ''))})") if data.get("id") else (False, "invalid token")
        except MetaAPIError as e:
            logger.warning("Facebook validate failed: graph error %s", e.status_code)
            return False, f"graph error {e.status_code}"

    # ------------------------------------------------------------------
    # Page hub reads + writes. All calls take the PAGE token from the
    # asset row. Reads pass params=; writes pass data= â€” Graph's canonical
    # encoding for bracket keys like attached_media[0][media_fbid] is
    # form data, and JSON bodies with bracket keys are unreliable.
    # MetaAPIError propagates from every method: a failed write must
    # surface, never silently vanish.

    async def get_page_profile(self, page_id: str, token: str) -> dict:
        resp = await self._graph(
            "GET", f"/{page_id}", token,
            params={"fields": "name,fan_count,followers_count,link,picture.type(large)"},
        )
        return resp.json()

    async def get_page_feed(self, page_id: str, token: str, limit: int = 25) -> list[dict]:
        resp = await self._graph(
            "GET", f"/{page_id}/feed", token,
            params={
                "fields": (
                    "id,message,created_time,permalink_url,full_picture,"
                    "from{id,name},"
                    "likes.summary(true).limit(0),comments.summary(true).limit(0),"
                    "attachments{title,unshimmed_url,media_type,subattachments{media}}"
                ),
                "limit": limit,
            },
        )
        return resp.json().get("data", [])

    async def get_scheduled_posts(self, page_id: str, token: str) -> list[dict]:
        resp = await self._graph(
            "GET", f"/{page_id}/scheduled_posts", token,
            params={"fields": "id,scheduled_publish_time"},
        )
        return resp.json().get("data", [])

    async def publish_post(self, *args, **kwargs) -> dict:
        """POST /{page}/feed for one destination+format."""
        # --- Resolve calling convention ---
        if "token" in kwargs and (
            "asset_id" in kwargs
            or "method" in kwargs
            or "media_url" in kwargs
            or "caption" in kwargs
            or "description" in kwargs
        ):
            token = kwargs["token"]
            asset_id = kwargs.get("asset_id")
            if asset_id is None and len(args) >= 1:
                asset_id = args[0]
            caption = kwargs.get("caption") or ""
            description = kwargs.get("description") or ""
            media_url = kwargs.get("media_url")
            scheduled_at = kwargs.get("scheduled_at")
            page_id = asset_id
            message = caption or description or ""
            data = {}
            if message:
                data["message"] = str(message)[:5000]
            attach_fbids = []
            if media_url:
                photo = await self.publish_photo(
                    page_id, token, url=media_url, caption=caption or None,
                    published=False,
                )
                fbid = photo.get("id")
                if fbid:
                    attach_fbids.append(fbid)
            for i, fbid in enumerate(attach_fbids):
                data[f"attached_media[{i}][media_fbid]"] = fbid
        else:
            page_id = kwargs.get("asset_id")
            if page_id is None and len(args) >= 1:
                page_id = args[0]
            token = kwargs.get("token")
            if token is None and len(args) >= 2:
                token = args[1]
            message = kwargs.get("message")
            attached_media = kwargs.get("attached_media")
            link = kwargs.get("link")
            scheduled_at = kwargs.get("scheduled_at")
            data = {}
            if message:
                data["message"] = str(message)[:5000]
            if link:
                data["link"] = str(link)
            for i, fbid in enumerate(attached_media or []):
                data[f"attached_media[{i}][media_fbid]"] = fbid

        if scheduled_at is not None and scheduled_at != "":
            unix = None
            if isinstance(scheduled_at, (int, float)):
                unix = int(scheduled_at)
            else:
                sval = str(scheduled_at).strip()
                if sval.isdigit():
                    unix = int(sval)
                else:
                    from datetime import datetime as _dt
                    try:
                        dt = _dt.fromisoformat(sval.replace("Z", "+00:00"))
                        unix = int(dt.timestamp())
                    except ValueError:
                        unix = None
            if unix is not None:
                data["published"] = "false"
                data["scheduled_publish_time"] = str(unix)

        resp = await self._graph("POST", f"/{page_id}/feed", token, data=data)
        return resp.json()

    async def publish_photo(
        self,
        page_id: str,
        token: str,
        *,
        url: str,
        caption: str | None = None,
        published: bool = True,
    ) -> dict:
        """POST /{page}/photos. A published photo returns {id, post_id};
        an unpublished (carousel child) returns {id} only."""
        data = {"url": url, "published": "true" if published else "false"}
        if caption:
            data["caption"] = caption
        resp = await self._graph("POST", f"/{page_id}/photos", token, data=data)
        return resp.json()

    async def reply_to_comment(self, comment_id: str, token: str, message: str) -> str:
        resp = await self._graph(
            "POST", f"/{comment_id}/comments", token, data={"message": message},
        )
        return resp.json().get("id", "")

    async def set_comment_hidden(self, comment_id: str, token: str, hidden: bool) -> None:
        await self._graph(
            "POST", f"/{comment_id}", token, data={"hidden": "true" if hidden else "false"},
        )

    async def delete_comment(self, comment_id: str, token: str) -> None:
        await self._graph("DELETE", f"/{comment_id}", token)

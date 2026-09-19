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

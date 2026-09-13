"""Instagram adapter (FB-Login stack: IG Professional via its Facebook Page).

Auth reuses the Facebook Login for Business connection; this adapter
discovers the linked IG business account per Page and validates API
eligibility at connect time.
"""
import logging

from .base import DiscoveredAsset, MetaAPIError, MetaProviderAdapter

logger = logging.getLogger(__name__)


class InstagramAdapter(MetaProviderAdapter):
    provider = "instagram"

    def build_auth_entry(self, state: str) -> dict:
        # Instagram uses the Facebook Login for Business flow; the tenant
        # connects Facebook first, then links the IG account to a Page.
        from .facebook import FacebookAdapter

        entry = FacebookAdapter().build_auth_entry(state)
        entry["note"] = "Connect Facebook first, then select the linked Instagram account."
        return entry

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
        """Validate the IG account can use the API (professional + public)."""
        try:
            resp = await self._graph(
                "GET",
                f"/{ig_id}",
                token,
                params={"fields": "id,username,account_type,media_count"},
            )
        except MetaAPIError as e:
            return False, f"graph error {e.status_code}"
        data = resp.json()
        if (data.get("account_type") or "").upper() not in ("BUSINESS", "CREATOR", "MEDIA_CREATOR"):
            return False, "not a Business/Creator account — switch in Instagram settings"
        return True, f"eligible (@{data.get('username', ig_id)})"

    async def validate_connection(self, connection, credentials: dict) -> tuple[bool, str]:
        token = credentials.get("access_token", "")
        if not token:
            return False, "missing token"
        try:
            resp = await self._graph("GET", "/me/accounts", token, params={"limit": 1})
            return (True, "ok") if resp.status_code == 200 else (False, "invalid token")
        except MetaAPIError as e:
            return False, f"graph error {e.status_code}"

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

    # ── Profile (READ ONLY) ──────────────────────────────────
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

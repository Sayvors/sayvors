"""WhatsApp Cloud API adapter (Tech Provider / Embedded Signup v4).

Tenant flow: frontend FB.login with the Builder config_id -> session gives
waba_id / phone_number_id / business_id + auth code -> backend exchanges the
code for a customer business token, subscribes webhooks, registers the
number, and persists WABA + phone_number assets.
"""
import logging

from .....config import settings
from .base import DiscoveredAsset, MetaAPIError, MetaProviderAdapter

logger = logging.getLogger(__name__)


class WhatsAppAdapter(MetaProviderAdapter):
    provider = "whatsapp"

    def build_auth_entry(self, state: str) -> dict:
        if not settings.META_APP_ID or not settings.META_WHATSAPP_CONFIG_ID:
            raise MetaAPIError(
                "WhatsApp onboarding not configured. Set META_APP_ID / "
                "META_WHATSAPP_CONFIG_ID in .env",
                503,
            )
        return {
            "fb_app_id": settings.META_APP_ID,
            "fb_config_id": settings.META_WHATSAPP_CONFIG_ID,
            "graph_api_version": settings.META_GRAPH_API_VERSION or "v26.0",
            # v4 Tech Provider flow extras (app_only_install). Empty when the
            # tenant isn't a Tech Provider — the frontend falls back to the
            # plain Embedded Signup extras then.
            "solution_id": settings.META_SOLUTION_ID or None,
            "state": state,
        }

    async def exchange_code(self, code: str, redirect_uri: str | None = None) -> dict:
        """Exchange the Embedded Signup auth code for a business token."""
        if not settings.META_APP_ID or not settings.META_APP_SECRET:
            raise MetaAPIError("Meta app not configured (META_APP_ID/SECRET)", 503)
        version = settings.META_GRAPH_API_VERSION or "v26.0"
        resp = await self._http.get(
            f"https://graph.facebook.com/{version}/oauth/access_token",
            params={
                "client_id": settings.META_APP_ID,
                "client_secret": settings.META_APP_SECRET,
                "code": code,
            },
        )
        if resp.status_code != 200:
            raise MetaAPIError(
                f"WhatsApp code exchange failed ({resp.status_code}): "
                f"{resp.text[:300]}",
                401,
            )
        return resp.json()  # {access_token, ...}

    async def discover_assets(self, credentials: dict) -> list[DiscoveredAsset]:
        """List WABAs + phone numbers visible to the business token."""
        token = credentials.get("access_token", "")
        business_id = credentials.get("business_id", "")
        out: list[DiscoveredAsset] = []
        if business_id:
            resp = await self._graph(
                "GET",
                f"/{business_id}/owned_whatsapp_business_accounts",
                token,
            )
            for waba in resp.json().get("data", []):
                waba_id = waba.get("id", "")
                out.append(
                    DiscoveredAsset(
                        asset_type="waba",
                        external_asset_id=waba_id,
                        name=waba.get("name"),
                        extra={"business_id": business_id},
                    )
                )
                numbers = await self._graph(
                    "GET", f"/{waba_id}/phone_numbers", token
                )
                for num in numbers.json().get("data", []):
                    out.append(
                        DiscoveredAsset(
                            asset_type="phone_number",
                            external_asset_id=num.get("id", ""),
                            parent_external_id=waba_id,
                            name=num.get("verified_name"),
                            phone=num.get("display_phone_number"),
                            extra={"business_id": business_id},
                        )
                    )
        else:
            # Fallback: session-provided ids only (no business context).
            if credentials.get("waba_id"):
                out.append(
                    DiscoveredAsset(
                        asset_type="waba",
                        external_asset_id=credentials["waba_id"],
                    )
                )
            if credentials.get("phone_number_id"):
                out.append(
                    DiscoveredAsset(
                        asset_type="phone_number",
                        external_asset_id=credentials["phone_number_id"],
                        parent_external_id=credentials.get("waba_id"),
                    )
                )
        logger.info("WhatsApp asset discovery: %d assets", len(out))
        return out

    async def subscribe_app(self, waba_id: str, token: str) -> None:
        await self._graph("POST", f"/{waba_id}/subscribed_apps", token)
        logger.info("WhatsApp subscribed_apps ok waba=%s", waba_id)

    async def register_number(self, phone_number_id: str, token: str, pin: str | None = None) -> None:
        body: dict = {"messaging_product": "whatsapp"}
        if pin:
            body["pin"] = pin
        await self._graph("POST", f"/{phone_number_id}/register", token, json=body)

    async def send_text_message(
        self, phone_number_id: str, token: str, to: str, text: str
    ) -> str:
        """Send a session (24h-window) text message. Returns provider message id."""
        resp = await self._graph(
            "POST",
            f"/{phone_number_id}/messages",
            token,
            json={
                "messaging_product": "whatsapp",
                "to": to,
                "type": "text",
                "text": {"body": text[:4000]},
            },
        )
        data = resp.json()
        msgs = data.get("messages", [])
        return msgs[0].get("id", "") if msgs else ""

    async def validate_connection(self, connection, credentials: dict) -> tuple[bool, str]:
        token = credentials.get("access_token", "")
        if not token:
            return False, "missing token"
        try:
            resp = await self._graph("GET", "/debug_token", token, params={"input_token": token})
            info = resp.json().get("data", {})
            if not info.get("is_valid"):
                return False, "token invalid"
            return True, "token valid"
        except MetaAPIError as e:
            logger.warning("WhatsApp validate failed: graph error %s", e.status_code)
            return False, f"graph error {e.status_code}"

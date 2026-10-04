"""WhatsApp Cloud API adapter (Tech Provider / Embedded Signup v4).

Tenant flow: frontend FB.login with the Builder config_id -> session gives
waba_id / phone_number_id / business_id + auth code -> backend exchanges the
code for a customer business token, subscribes webhooks, registers the
number, and persists WABA + phone_number assets.
"""
import logging

from .....config import settings
from .base import DiscoveredAsset, MetaAPIError, MetaProviderAdapter, graph_base

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
            # Coexistence ("Connect existing") runs a different Builder
            # configuration — the merchant keeps their own number and app, so
            # Meta must not show the new-number onboarding. The frontend picks
            # this one when the tenant chose coexistence. Falls back to the
            # standard config only if it was left unset.
            "fb_coexistence_config_id": (
                settings.META_WHATSAPP_COEXISTENCE_CONFIG_ID
                or settings.META_WHATSAPP_CONFIG_ID
            ),
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
        """Register the number on the Cloud API (idempotent).

        Meta REQUIRES a 6-digit two-step-verification PIN here — without it
        the call fails with an onboarding error and the number cannot send
        until registration succeeds. The PIN is the tenant's own, supplied
        during Embedded Signup or via the register-retry endpoint.
        """
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

    async def upload_media(
        self, phone_number_id: str, token: str, data: bytes, mime_type: str
    ) -> str:
        """Upload media for this number; returns the media id for sends."""
        resp = await self._http.post(
            f"{graph_base()}/{phone_number_id}/media",
            headers={"Authorization": f"Bearer {token}"},
            data={"messaging_product": "whatsapp", "type": mime_type},
            files={"file": ("audio", data, mime_type)},
        )
        if resp.status_code >= 400:
            raise MetaAPIError(
                f"WhatsApp media upload failed ({resp.status_code}): {resp.text[:300]}",
                resp.status_code,
            )
        return resp.json().get("id", "")

    async def send_voice_note(
        self, phone_number_id: str, token: str, to: str, media_id: str,
        voice: bool = True,
    ) -> str:
        """Send an uploaded audio. voice=True (Ogg/Opus required) renders as
        a real voice note — mic bubble, waveform, hands-free playback —
        instead of a generic media file. Returns message id."""
        audio: dict = {"id": media_id}
        if voice:
            audio["voice"] = True
        resp = await self._graph(
            "POST",
            f"/{phone_number_id}/messages",
            token,
            json={
                "messaging_product": "whatsapp",
                "to": to,
                "type": "audio",
                "audio": audio,
            },
        )
        data = resp.json()
        msgs = data.get("messages", [])
        return msgs[0].get("id", "") if msgs else ""

    async def send_typing_indicator(
        self, phone_number_id: str, token: str, message_id: str
    ) -> bool:
        """Mark the inbound message read and show the typing dots while we
        prepare the reply (the Cloud API has no 'recording audio' variant).
        Best-effort: False on any failure — cosmetics must never break a
        reply."""
        try:
            await self._http.post(
                f"{graph_base()}/{phone_number_id}/messages",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "messaging_product": "whatsapp",
                    "status": "read",
                    "message_id": message_id,
                    "typing_indicator": {"type": "text"},
                },
            )
            return True
        except Exception as e:
            logger.info("Typing indicator failed: %s: %s", type(e).__name__, str(e)[:120])
            return False

    async def sync_smb_app_data(
        self, phone_number_id: str, token: str, sync_type: str
    ) -> None:
        """Trigger SMB App Data sync (contacts or history).

        Must be called within 24h of coexistence onboarding.
        sync_type: "smb_app_state_sync" (contacts) or "history" (messages).
        """
        await self._graph(
            "POST",
            f"/{phone_number_id}/smb_app_data",
            token,
            json={"messaging_product": "whatsapp", "sync_type": sync_type},
        )
        logger.info(
            "WhatsApp SMB app data sync triggered phone=%s type=%s",
            phone_number_id, sync_type,
        )

    async def validate_connection(self, connection, credentials: dict) -> tuple[bool, str]:
        """True when the token can still read the business's WABAs.

        /debug_token self-inspection is NOT usable here: the Embedded Signup
        code exchange yields a business token, and Graph answers a business
        token passed as the caller credential on /debug_token with a 400 —
        which marked fresh, working connections "needs_reauth" while the same
        token was fine for messaging. Ask for something we actually use.
        """
        token = credentials.get("access_token", "")
        if not token:
            return False, "missing token"
        business_id = (
            getattr(connection, "meta_business_id", None)
            or (connection.connection_metadata or {}).get("business_id")
        )
        if not business_id:
            return False, "no business id on connection"
        try:
            resp = await self._graph(
                "GET", f"/{business_id}/owned_whatsapp_business_accounts", token
            )
        except MetaAPIError as e:
            logger.warning("WhatsApp validate failed: graph error %s", e.status_code)
            return False, f"graph error {e.status_code}"
        return True, f"{len(resp.json().get('data', []))} WABA(s) visible"

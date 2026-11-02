"""Meta provider adapter interface (WhatsApp / Facebook / Instagram)."""
import asyncio
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import httpx

from .....config import settings


class MetaAPIError(Exception):
    def __init__(self, message: str, status_code: int = 502, payload: dict | None = None):
        self.status_code = status_code
        self.payload = payload or {}
        super().__init__(message)


class MetaTransportError(MetaAPIError):
    """Meta was unreachable — the connect phase failed after bounded retries.

    Carries status 503 so every existing ``status_code >= 500`` transient
    branch (consumer reply sites, the lead-action worker, the events worker's
    generic retry) treats it as retryable. Raised only for connect-phase
    failures: the request provably never reached Meta, so a retry cannot
    double-send.
    """

    def __init__(self, message: str, payload: dict | None = None):
        super().__init__(message, 503, payload)


class MetaAmbiguousError(Exception):
    """The request reached (or may have reached) Meta, but the outcome is
    unknown — read timeout, connection broke mid-response, write error.

    Never auto-retried: Meta's send API has no idempotency key, so a blind
    retry can double-message a customer. Callers keep their pending row and
    re-raise so the events worker files the event ``ambiguous`` (terminal) —
    the same doctrine lead_action_worker applies to follow-up nudges.
    """


class MetaPermanentError(Exception):
    """Config/credential problem — retrying cannot help."""

    def __init__(self, message: str, status_code: int = 400):
        self.status_code = status_code
        super().__init__(message)


# Transport policy for _graph. Connect-phase failures are retried in place
# with a small capped backoff: the request provably never left, so a bounded
# retry cannot double-send. Once the request is on the wire (read timeouts,
# broken responses, write errors) the outcome is unknown and is raised as
# MetaAmbiguousError — retry decisions belong to the callers' taxonomy
# (transient/permanent/ambiguous in the events worker), not to the HTTP
# layer. HTTP-level 429/5xx are answered by Meta, so they surface as plain
# MetaAPIError and keep their caller-specific handling.
TRANSIENT_CONNECT_ERRORS = (httpx.ConnectError, httpx.ConnectTimeout)
GRAPH_CONNECT_ATTEMPTS = 3
GRAPH_CONNECT_BACKOFF_SECONDS = (0.5, 1.5)


def graph_base() -> str:
    return f"https://graph.facebook.com/{settings.META_GRAPH_API_VERSION or 'v26.0'}"


@dataclass
class DiscoveredAsset:
    """One asset found on the provider side, awaiting tenant selection."""

    asset_type: str  # waba | phone_number | page | ig_account
    external_asset_id: str
    parent_external_id: str | None = None
    name: str | None = None
    username: str | None = None
    phone: str | None = None
    extra: dict = field(default_factory=dict)


class MetaProviderAdapter(ABC):
    provider: str = ""

    def __init__(self):
        self._http = httpx.AsyncClient(timeout=20.0)

    async def close(self) -> None:
        await self._http.aclose()

    @abstractmethod
    def build_auth_entry(self, state: str) -> dict:
        """Return connect entry: {auth_url} or {fb_app_id, fb_config_id, ...}."""

    @abstractmethod
    async def exchange_code(self, code: str, redirect_uri: str | None = None) -> dict:
        """Exchange an auth code for credentials. Returns token fields."""

    @abstractmethod
    async def discover_assets(self, credentials: dict) -> list[DiscoveredAsset]:
        """List connectable assets for the authorized business."""

    @abstractmethod
    async def validate_connection(self, connection, credentials: dict) -> tuple[bool, str]:
        """Lightweight health check. Returns (ok, detail)."""

    async def _graph(
        self, method: str, path: str, token: str, **kwargs
    ) -> httpx.Response:
        headers = dict(kwargs.pop("headers", {}) or {})
        headers["Authorization"] = f"Bearer {token}"
        url = f"{graph_base()}{path}"
        for attempt in range(GRAPH_CONNECT_ATTEMPTS):
            try:
                resp = await self._http.request(method, url, headers=headers, **kwargs)
                break
            except TRANSIENT_CONNECT_ERRORS as exc:
                if attempt == GRAPH_CONNECT_ATTEMPTS - 1:
                    raise MetaTransportError(
                        f"Meta Graph {method} {path} unreachable after "
                        f"{GRAPH_CONNECT_ATTEMPTS} attempts: {exc}"
                    ) from exc
                base = GRAPH_CONNECT_BACKOFF_SECONDS[
                    min(attempt, len(GRAPH_CONNECT_BACKOFF_SECONDS) - 1)
                ]
                await asyncio.sleep(base * random.uniform(0.5, 1.5))
            except httpx.HTTPError as exc:
                # On the wire: the send may have landed. The honest answer is
                # "unknown" — callers file it ambiguous instead of retrying.
                raise MetaAmbiguousError(
                    f"Meta Graph {method} {path} failed mid-flight: "
                    f"{type(exc).__name__}: {exc}"
                ) from exc
        if resp.status_code >= 400:
            raise MetaAPIError(
                f"Meta Graph {method} {path} failed ({resp.status_code}): "
                f"{resp.text[:300]}",
                resp.status_code,
            )
        return resp

    async def publish_post(
        self,
        token: str,
        asset_id: str,
        method: str,
        media_url: str | None,
        media_type: str | None,
        caption: str,
        description: str,
        scheduled_at: str | None,
    ) -> dict:
        """Publish one post to one destination+format.

        Subclasses implement the provider-specific Graph API call.
        Returns a provider-native result dict.
        """
        raise NotImplementedError(f"{self.provider} does not implement publish_post")

"""Meta provider adapter interface (WhatsApp / Facebook / Instagram)."""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import httpx

from .....config import settings


class MetaAPIError(Exception):
    def __init__(self, message: str, status_code: int = 502, payload: dict | None = None):
        self.status_code = status_code
        self.payload = payload or {}
        super().__init__(message)


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
        resp = await self._http.request(method, f"{graph_base()}{path}", headers=headers, **kwargs)
        if resp.status_code >= 400:
            raise MetaAPIError(
                f"Meta Graph {method} {path} failed ({resp.status_code}): "
                f"{resp.text[:300]}",
                resp.status_code,
            )
        return resp

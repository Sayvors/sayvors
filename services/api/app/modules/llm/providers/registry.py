import inspect
import logging
import time

from .base import LLMProvider, ProviderError
from .catalog import MODELS, ModelInfo, get_model_by_id, get_provider_from_model
from .openai_compatible import OpenAICompatibleProvider
from .gemini import GeminiProvider

logger = logging.getLogger(__name__)

_providers: dict[str, LLMProvider] = {}

# In-memory overlay from llm_provider_configs (database is the only source).
# None = not loaded yet (behaves exactly like "no rows"); refresh on boot
# and on every admin save. Tests can reset via reset_provider_cache().
_db_overlay: dict[str, dict] | None = None

# Per-model admin curation: model_id -> enabled. Absent = follow provider.
# Loaded alongside the provider overlay; write-through on admin toggle.
_model_overlay: dict[str, bool] | None = None

# Admin-defined custom models: model_id -> full definition dict.
# Loaded alongside the overlays; merged over the code catalog.
_custom_models: dict[str, dict] | None = None

# Every uvicorn worker has its own overlay. An admin save reaches only the
# worker that handled the request, so the others refresh when their copy is
# older than this. 15s keeps key rotation fast without a DB query per call.
PROVIDER_KEY_REFRESH_SECONDS = 15.0
_last_refresh = 0.0
_last_attempt = 0.0

PROVIDER_CONFIGS: dict[str, dict] = {
    "openai": {},
    "grok": {},
    "kimi": {},
    "deepseek": {},
    "groq": {},
    "openrouter": {},
    "ollama": {"optional": True},
    "gemini": {},
}


def resolve_provider_key(provider: str) -> tuple[str | None, str]:
    """Effective API key + where it came from: database | none | disabled.

    Database-only by design (admin-managed). Never raises, never logs key
    values — the key itself only flows into provider constructors.
    """
    if provider not in PROVIDER_CONFIGS:
        return None, "none"
    if _db_overlay is not None and provider in _db_overlay:
        entry = _db_overlay[provider] or {}
        if not entry.get("enabled", True):
            return None, "disabled"
        enc = entry.get("key_encrypted")
        if enc:
            try:
                from ...channels.service import decrypt_token

                key = decrypt_token(enc)
                if key:
                    return key, "database"
            except Exception:
                pass
    return None, "none"


async def refresh_provider_keys(session_factory=None) -> int:
    """(Re)load DB provider keys + model curation into the overlays.

    Returns provider row count. Database is the single source of truth —
    env vars are never consulted. Drops cached provider instances so
    rotated/disabled keys take effect on next use. Safe to call repeatedly
    (admin save, boot).
    """
    from ....database import async_session

    factory = session_factory or async_session
    async with factory() as db:
        return await refresh_provider_keys_from_session(db)


async def _close_provider(provider: LLMProvider) -> None:
    """Best-effort close of a provider's HTTP client.

    Key rotation replaces the cached provider; dropping an ``AsyncOpenAI``
    without closing it strands its connection pool until GC. The Gemini client
    is synchronous, so both signatures are handled.
    """
    client = getattr(provider, "_client", None)
    if client is None:
        return
    for name in ("aclose", "close"):
        close = getattr(client, name, None)
        if close is None:
            continue
        try:
            result = close()
            if inspect.isawaitable(result):
                await result
        except Exception as e:
            logger.debug("Provider client close failed: %s", e)
        return


async def refresh_provider_keys_from_session(db) -> int:
    """Load the overlays from a session the caller already owns.

    Admin endpoints pass the request session so a key saved in one worker is
    visible immediately there, and tests read their own database instead of
    opening the process-wide session.
    """
    global _db_overlay, _model_overlay, _custom_models, _last_refresh
    from sqlalchemy import select

    from ..models import ModelConfig, ProviderConfig

    rows = (await db.execute(select(ProviderConfig))).scalars().all()
    new_overlay = {
        r.provider: {"key_encrypted": r.key_encrypted, "enabled": r.enabled}
        for r in rows
    }
    # Only evict providers whose connection config actually changed. The TTL
    # refresh runs every 15s; rebuilding every client each time would churn
    # connection pools for no reason.
    previous = _db_overlay or {}
    changed = {
        name
        for name in set(previous) | set(new_overlay)
        if (previous.get(name) or {}).get("key_encrypted")
        != (new_overlay.get(name) or {}).get("key_encrypted")
        or bool((previous.get(name) or {}).get("enabled", True))
        != bool((new_overlay.get(name) or {}).get("enabled", True))
    }
    _db_overlay = new_overlay
    model_rows = (await db.execute(select(ModelConfig))).scalars().all()
    _model_overlay = {r.model_id: bool(r.enabled) for r in model_rows}
    _custom_models = {
        r.model_id: {
            "name": r.display_name or r.model_id,
            "provider": r.provider or "",
            "api_model": r.api_model or "",
            "context": r.context_window or 32000,
            "max_output": r.max_output or 4096,
            "supports_stream": bool(r.supports_stream) if r.supports_stream is not None else True,
        }
        for r in model_rows
        if r.provider and r.api_model
    }
    for name in changed:
        provider = _providers.pop(name, None)
        if provider is not None:
            await _close_provider(provider)
    _last_refresh = time.monotonic()
    return len(_db_overlay)


async def ensure_provider_keys_fresh() -> None:
    """Refresh the overlay when it is missing or older than the TTL.

    Each uvicorn worker holds its own copy. An admin save updates only the
    worker that handled the request; the TTL is how the others converge
    without a restart. A failed refresh keeps the previous overlay (or none)
    and is retried at most once per TTL so a database outage does not add a
    connection attempt to every model call.
    """
    global _last_attempt
    from ....config import settings

    # Tests seed the overlay explicitly; opening the process-wide session
    # here would read the developer database instead of the test database.
    if settings.TESTING:
        return

    now = time.monotonic()
    if _db_overlay is not None and (now - _last_refresh) < PROVIDER_KEY_REFRESH_SECONDS:
        return
    if (now - _last_attempt) < PROVIDER_KEY_REFRESH_SECONDS:
        return
    _last_attempt = now
    try:
        await refresh_provider_keys()
    except Exception as e:
        logger.warning(
            "Provider key refresh failed; keeping the previous overlay: %s", e
        )


def list_effective_models() -> list[ModelInfo]:
    """Code catalog merged with admin-defined custom models (DB wins on id)."""
    merged = {m.id: m for m in MODELS}
    for model_id, definition in (_custom_models or {}).items():
        merged[model_id] = ModelInfo(
            id=model_id,
            name=definition["name"],
            provider=definition["provider"],
            api_model=definition["api_model"],
            context=definition["context"],
            max_output=definition["max_output"],
            supports_stream=definition["supports_stream"],
        )
    return list(merged.values())


def get_effective_model(model_id: str) -> ModelInfo | None:
    """Custom-row first, then the code catalog."""
    custom = (_custom_models or {}).get(model_id)
    if custom:
        return ModelInfo(
            id=model_id,
            name=custom["name"],
            provider=custom["provider"],
            api_model=custom["api_model"],
            context=custom["context"],
            max_output=custom["max_output"],
            supports_stream=custom["supports_stream"],
        )
    return get_model_by_id(model_id)


def is_model_enabled(model_id: str) -> bool:
    """Admin per-model curation. Absent row (or unloaded overlay) = follow provider."""
    if _model_overlay is None:
        return True
    return _model_overlay.get(model_id, True)


def reset_provider_cache() -> None:
    """Test helper: clear overlays + instances."""
    global _db_overlay, _model_overlay, _custom_models, _last_refresh, _last_attempt
    _db_overlay = None
    _model_overlay = None
    _custom_models = None
    _last_refresh = 0.0
    _last_attempt = 0.0
    _providers.clear()


def get_provider(provider: str) -> LLMProvider:
    if provider in _providers:
        return _providers[provider]

    if provider not in PROVIDER_CONFIGS:
        raise ProviderError(provider, f"Unknown provider: {provider}", 400)
    config = PROVIDER_CONFIGS[provider]

    api_key, source = resolve_provider_key(provider)
    optional = config.get("optional", False)

    if source == "disabled":
        raise ProviderError(provider, f"Provider {provider} is disabled by admin.", 503)
    if not api_key and not optional:
        raise ProviderError(
            provider,
            f"API key not configured for {provider}. Add it in Admin → LLMs.",
            503,
        )

    if provider == "gemini":
        inst = GeminiProvider(api_key=api_key or "")
    else:
        if not api_key:
            api_key = "ollama"  # Ollama doesn't require a real key
        inst = OpenAICompatibleProvider(provider=provider, api_key=api_key)

    _providers[provider] = inst
    return inst


def get_provider_for_model(model_id: str) -> LLMProvider:
    custom = (_custom_models or {}).get(model_id)
    provider_key = custom["provider"] if custom else get_provider_from_model(model_id)
    return get_provider(provider_key)


def list_models() -> list[ModelInfo]:
    return MODELS


async def list_tenant_models(db) -> list[tuple[ModelInfo, str]]:
    """What tenants may see and pick: ONLY admin-saved rows.

    A model reaches a tenant iff ALL hold:
      1. an `llm_model_configs` row exists with enabled=true
         (custom definition, or an explicit opt-in of a catalog model),
      2. its provider is not disabled by admin,
      3. its provider has a usable key (ollama needs none — local server).

    Reads the request's DB session directly, so the tenant list always
    reflects what the database holds right now — never the code catalog,
    never a stale overlay.
    Returns (ModelInfo, key_source) pairs; every item is usable.
    """
    from sqlalchemy import select

    from ..models import ModelConfig, ProviderConfig

    prov_rows = (await db.execute(select(ProviderConfig))).scalars().all()
    providers = {r.provider: r for r in prov_rows}

    def _usable_source(provider: str) -> str | None:
        row = providers.get(provider)
        if row is not None and not row.enabled:
            return None
        if provider == "ollama":
            return "local"
        enc = row.key_encrypted if row is not None else None
        if not enc:
            return None
        try:
            from ...channels.service import decrypt_token

            key = decrypt_token(enc)
        except Exception:
            return None
        return "database" if key else None

    saved = (
        (await db.execute(select(ModelConfig).where(ModelConfig.enabled.is_(True))))
        .scalars()
        .all()
    )
    out: list[tuple[ModelInfo, str]] = []
    for row in sorted(saved, key=lambda r: r.model_id):
        if row.provider and row.api_model:
            info = ModelInfo(
                id=row.model_id,
                name=row.display_name or row.model_id,
                provider=row.provider,
                api_model=row.api_model,
                context=row.context_window or 32000,
                max_output=row.max_output or 4096,
                supports_stream=row.supports_stream
                if row.supports_stream is not None
                else True,
            )
        else:
            base = get_model_by_id(row.model_id)
            if base is None:
                continue
            info = ModelInfo(
                id=base.id,
                name=row.display_name or base.name,
                provider=base.provider,
                api_model=base.api_model,
                context=base.context,
                max_output=base.max_output,
                supports_stream=base.supports_stream,
            )
        source = _usable_source(info.provider)
        if source is None:
            continue
        out.append((info, source))
    return out

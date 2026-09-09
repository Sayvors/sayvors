from ....config import settings
from .base import LLMProvider, ProviderError
from .catalog import MODELS, ModelInfo, get_provider_from_model
from .openai_compatible import OpenAICompatibleProvider
from .gemini import GeminiProvider

_providers: dict[str, LLMProvider] = {}

PROVIDER_CONFIGS: dict[str, dict] = {
    "openai": {"key": "OPENAI_API_KEY"},
    "grok": {"key": "XAI_API_KEY"},
    "kimi": {"key": "MOONSHOT_API_KEY"},
    "deepseek": {"key": "DEEPSEEK_API_KEY"},
    "groq": {"key": "GROQ_API_KEY"},
    "ollama": {"key": "OLLAMA_API_KEY", "optional": True},
    "gemini": {"key": "GEMINI_API_KEY"},
}


def _get_api_key(config: dict) -> str | None:
    return getattr(settings, config["key"], None)


def get_provider(provider: str) -> LLMProvider:
    if provider in _providers:
        return _providers[provider]

    config = PROVIDER_CONFIGS.get(provider)
    if not config:
        raise ProviderError(provider, f"Unknown provider: {provider}", 400)

    api_key = _get_api_key(config)
    optional = config.get("optional", False)

    if not api_key and not optional:
        raise ProviderError(
            provider,
            f"API key not configured for {provider}. Set {config['key']} in .env",
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
    provider_key = get_provider_from_model(model_id)
    return get_provider(provider_key)


def list_models() -> list[ModelInfo]:
    return MODELS

"""GroqCloud provider wiring (no network — resolution only)."""
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.config import settings
from app.modules.llm.providers import base as provider_base
from app.modules.llm.providers import catalog, registry
from app.modules.llm.providers.openai_compatible import (
    PROVIDER_BASE_URLS,
    OpenAICompatibleProvider,
)
from app.modules.llm.service import _resolve_model


def test_groq_base_url_registered():
    assert PROVIDER_BASE_URLS["groq"] == "https://api.groq.com/openai/v1"


def test_groq_models_in_catalog():
    ids = [m.id for m in catalog.MODELS]
    assert "groq:oss-120b" in ids
    assert "groq:oss-20b" in ids
    info = catalog.get_model_by_id("groq:oss-120b")
    assert info is not None
    assert info.provider == "groq"
    assert info.api_model == "openai/gpt-oss-120b"


def test_resolve_model_maps_groq_id():
    api_model, provider = _resolve_model("groq:oss-120b")
    assert api_model == "openai/gpt-oss-120b"
    assert provider == "groq"


def test_groq_missing_key_fails_fast(monkeypatch):
    monkeypatch.setattr(settings, "GROQ_API_KEY", "")
    registry._providers.pop("groq", None)
    try:
        registry.get_provider("groq")
    except provider_base.ProviderError as e:
        assert e.status_code == 503
    else:
        raise AssertionError("expected ProviderError 503 without key")


def test_groq_provider_builds_with_key(monkeypatch):
    monkeypatch.setattr(settings, "GROQ_API_KEY", "gsk_test_key")
    registry._providers.pop("groq", None)
    try:
        inst = registry.get_provider("groq")
        assert isinstance(inst, OpenAICompatibleProvider)
        assert inst.name() == "groq"
    finally:
        registry._providers.pop("groq", None)


def test_db_pool_fail_fast_defaults():
    assert settings.DB_POOL_SIZE >= 5
    assert settings.DB_POOL_MAX_OVERFLOW >= 0
    assert settings.DB_POOL_TIMEOUT_SECONDS > 0

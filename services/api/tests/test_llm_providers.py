"""DB-backed LLM provider keys: precedence, kill-switch, refresh (no network)."""
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.modules.channels.service import encrypt_token
from app.modules.llm.providers import registry
from app.modules.llm.providers.base import ProviderError


@pytest.fixture(autouse=True)
def _clean_registry():
    registry.reset_provider_cache()
    yield
    registry.reset_provider_cache()


def _factory(rows, model_rows=None):
    """Stateful fake DB: provider rows + model rows, routed by table name."""
    store = {r.provider: r for r in rows}
    models = {r.model_id: r for r in (model_rows or [])}

    @asynccontextmanager
    async def _make():
        class _Session:
            async def execute(self, stmt):
                table = "models" if "llm_model_configs" in str(stmt) else "providers"

                class _R:
                    def scalars(inner_self):
                        class _S:
                            def all(inner_self2):
                                return list(models.values() if table == "models" else store.values())

                        return _S()

                return _R()

            def add(self, obj):
                if hasattr(obj, "model_id"):
                    models[obj.model_id] = obj
                else:
                    store[obj.provider] = obj

            async def commit(self):
                pass

        yield _Session()

    return _make


@pytest.mark.asyncio
async def test_no_key_anywhere_means_none():
    key, source = registry.resolve_provider_key("groq")
    assert (key, source) == (None, "none")
    with pytest.raises(ProviderError):
        registry.get_provider("groq")


@pytest.mark.asyncio
async def test_refresh_loads_only_db_rows():
    # Env vars are never consulted — even with keys sitting in the
    # environment, resolution stays database-only.
    import os

    os.environ["GROQ_API_KEY"] = "gsk_should_be_ignored"
    try:
        n = await registry.refresh_provider_keys(session_factory=_factory([]))
        assert n == 0
        key, source = registry.resolve_provider_key("groq")
        assert (key, source) == (None, "none")
    finally:
        del os.environ["GROQ_API_KEY"]


@pytest.mark.asyncio
async def test_disabled_kill_switch():
    enc = encrypt_token("gsk_db")
    await registry.refresh_provider_keys(
        session_factory=_factory([SimpleNamespace(
            provider="groq", key_encrypted=enc, enabled=False
        )])
    )
    key, source = registry.resolve_provider_key("groq")
    assert (key, source) == (None, "disabled")
    with pytest.raises(ProviderError):
        registry.get_provider("groq")


@pytest.mark.asyncio
async def test_get_provider_uses_db_key():
    enc = encrypt_token("gsk_db")
    await registry.refresh_provider_keys(
        session_factory=_factory([SimpleNamespace(
            provider="groq", key_encrypted=enc, enabled=True
        )])
    )
    inst = registry.get_provider("groq")
    assert inst.name() == "groq"
    assert inst._client.api_key == "gsk_db"


@pytest.mark.asyncio
async def test_unknown_provider():
    key, source = registry.resolve_provider_key("nope")
    assert (key, source) == (None, "none")
    with pytest.raises(ProviderError):
        registry.get_provider("nope")


def test_custom_models_merge_over_catalog():
    from app.modules.llm.providers import registry as reg

    reg._custom_models = {
        "groq:my-custom": {
            "name": "My Custom", "provider": "groq", "api_model": "my-custom",
            "context": 8000, "max_output": 1000, "supports_stream": False,
        }
    }
    try:
        info = reg.get_effective_model("groq:my-custom")
        assert info is not None
        assert info.name == "My Custom"
        assert info.api_model == "my-custom"
        assert info.provider == "groq"
        # Catalog untouched for other ids.
        assert reg.get_effective_model("groq:oss-120b") is not None
        assert reg.get_effective_model("nope:missing") is None
        ids = [m.id for m in reg.list_effective_models()]
        assert "groq:my-custom" in ids
        assert len(ids) == len(set(ids))  # no duplicates
    finally:
        reg._custom_models = None


def test_custom_model_drives_provider_resolution(monkeypatch):
    from app.modules.channels.service import encrypt_token
    from app.modules.llm.providers import registry as reg

    monkeypatch.setattr(
        reg, "_custom_models",
        {"kimi:my-custom": {
            "name": "Mine", "provider": "kimi", "api_model": "kimi-custom",
            "context": 8000, "max_output": 1000, "supports_stream": True,
        }},
        raising=False,
    )
    monkeypatch.setattr(
        reg, "_db_overlay",
        {"kimi": {"key_encrypted": encrypt_token("k"), "enabled": True}},
        raising=False,
    )
    try:
        inst = reg.get_provider_for_model("kimi:my-custom")
        assert inst.name() == "kimi"
    finally:
        reg._custom_models = None

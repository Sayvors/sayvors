"""The LLM gateway is the only door to model generation.

Feature modules must not build ``LLMRequest`` objects or ask the provider
registry for an instance: those paths skip the required purpose, the budget
gate and the usage row. Tests may import provider internals to fake transport;
application code may not.
"""

import ast
import inspect
from pathlib import Path

import pytest

from app.modules.llm import gateway
from app.modules.llm import service as llm_service
from app.modules.llm.providers import registry
from app.modules.llm.providers.base import LLMMessage, LLMResponse, LLMUsage

_MODULES_ROOT = Path(__file__).resolve().parents[1] / "app" / "modules"
# Generation plumbing. Curation symbols (``list_tenant_models``,
# ``resolve_provider_key``) are allowed: they read configuration without
# spending tokens.
_FORBIDDEN_NAMES = {"LLMRequest", "LLMProvider", "get_provider_for_model", "_resolve_model"}
_PROVIDER_MODULES = (
    "app.modules.llm.providers.base",
    "app.modules.llm.providers.registry",
)


def _module_name(path: Path) -> str:
    rel = path.relative_to(_MODULES_ROOT.parent).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _resolve_relative(module: str | None, level: int, current: str) -> str:
    """Resolve ``from ..x import y`` against the file's own dotted module."""
    if level == 0:
        return module or ""
    base = current.split(".")[: -level]
    if module:
        base.append(module)
    return ".".join(base)


def _imports(path: Path):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    current = _module_name(path)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            target = _resolve_relative(node.module, node.level, current)
            for alias in node.names:
                yield target, alias.name, False
        elif isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, alias.name.rsplit(".", 1)[-1], True


def test_no_feature_module_reaches_into_generation_internals():
    offenders = []
    for path in _MODULES_ROOT.rglob("*.py"):
        parts = path.relative_to(_MODULES_ROOT).parts
        if parts and parts[0] == "llm":
            continue
        for target, name, is_module_import in _imports(path):
            if (
                not is_module_import
                and target == "app.modules.llm.service"
                and name == "_resolve_model"
            ):
                offenders.append(
                    f"{path.relative_to(_MODULES_ROOT)}: imports {target}.{name}"
                )
                continue
            if not target.startswith("app.modules.llm.providers"):
                continue
            if is_module_import and target in _PROVIDER_MODULES:
                offenders.append(
                    f"{path.relative_to(_MODULES_ROOT)}: imports {target}"
                )
            elif not is_module_import and target in _PROVIDER_MODULES and name in _FORBIDDEN_NAMES:
                offenders.append(
                    f"{path.relative_to(_MODULES_ROOT)}: from {target} import {name}"
                )
    assert not offenders, (
        "Generation internals imported outside the LLM gateway:\n"
        + "\n".join(offenders)
    )


@pytest.mark.parametrize("entrypoint", [gateway.complete, gateway.stream])
def test_purpose_is_required_and_keyword_only(entrypoint):
    purpose = inspect.signature(entrypoint).parameters["purpose"]
    assert purpose.kind is inspect.Parameter.KEYWORD_ONLY
    assert purpose.default is inspect.Parameter.empty


@pytest.mark.asyncio
async def test_complete_builds_metering_context(monkeypatch, engine):
    captured = {}

    class _Provider:
        async def complete(self, req):
            captured["req"] = req
            return LLMResponse(
                content="ok",
                provider="groq",
                model="api-x",
                usage=LLMUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            )

    monkeypatch.setattr(registry, "get_provider_for_model", lambda model: _Provider())
    monkeypatch.setattr(llm_service, "_resolve_model", lambda model: ("api-x", "groq"))

    resp = await gateway.complete(
        model="groq:custom",
        messages=[LLMMessage(role="user", content="hi")],
        purpose="test.boundary",
        tenant_id="tenant-1",
        temperature=0.2,
        max_tokens=64,
    )

    req = captured["req"]
    assert req.model == "api-x"
    assert req.model_id == "groq:custom"
    assert req.purpose == "test.boundary"
    assert req.tenant_id == "tenant-1"
    assert req.temperature == 0.2
    assert req.max_tokens == 64
    assert resp.content == "ok"


def test_resolve_model_returns_resolved_model():
    resolved = gateway.resolve_model("groq:oss-120b")
    assert isinstance(resolved, gateway.ResolvedModel)
    assert resolved.model_id == "groq:oss-120b"
    assert resolved.provider == "groq"
    assert resolved.api_model

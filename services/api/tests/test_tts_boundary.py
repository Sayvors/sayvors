"""The TTS module must stay extractable into its own service.

The one invariant that makes that possible today: nothing under
``app/modules/tts`` imports a channel module. Synthesis may not depend on the
transport that happens to call it first.
"""

import ast
from pathlib import Path

TTS_DIR = Path(__file__).resolve().parents[1] / "app" / "modules" / "tts"

# Capability modules an extracted TTS service must not need.
FORBIDDEN = {"channels", "posts", "localith", "analytics", "review_engine"}


def _imported_modules(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            yield node.lineno, node.module or ""
        elif isinstance(node, ast.Import):
            for alias in node.names:
                yield node.lineno, alias.name


def test_tts_does_not_import_channel_modules():
    offenders = []
    for path in sorted(TTS_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for lineno, module in _imported_modules(tree):
            parts = set(module.split("."))
            if parts & FORBIDDEN:
                offenders.append(f"{path.relative_to(TTS_DIR)}:{lineno} -> {module}")

    assert offenders == [], (
        "app/modules/tts must not depend on channel modules:\n  "
        + "\n  ".join(offenders)
    )


def test_tts_public_api_is_plain_data():
    """Callers serialize the request; keep it free of ORM objects."""
    from dataclasses import is_dataclass

    from app.modules.tts.api import SynthesisRequest, SynthesisResult

    assert is_dataclass(SynthesisRequest)
    assert is_dataclass(SynthesisResult)

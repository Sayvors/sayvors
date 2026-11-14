"""Streaming metering: providers must capture the final usage chunk so the
gateway can bill exact tokens instead of the char estimate."""
import pytest

from app.modules.llm.providers.openai_compatible import OpenAICompatibleProvider
from app.modules.llm.providers.gemini import GeminiProvider


def _req():
    from types import SimpleNamespace

    return SimpleNamespace(
        messages=[SimpleNamespace(role="user", content="hi")],
        system_prompt="",
        temperature=0.2,
        max_tokens=50,
        tools=None,
        model="gpt-4o-mini",
    )


class _Usage:
    def __init__(self, prompt, completion, total):
        self.prompt_tokens = prompt
        self.completion_tokens = completion
        self.total_tokens = total


class _Chunk:
    def __init__(self, content, usage=None):
        from types import SimpleNamespace

        self.choices = [SimpleNamespace(delta=SimpleNamespace(content=content))]
        self.usage = usage


class _Completions:
    async def create(self, **_kw):
        async def gen():
            yield _Chunk("Hel")
            yield _Chunk("lo", usage=_Usage(12, 2, 14))

        return gen()


class _Chat:
    completions = _Completions()


class _OpenAIClient:
    chat = _Chat()


async def test_openai_stream_captures_final_usage():
    provider = OpenAICompatibleProvider("openai", "x")
    provider._client = _OpenAIClient()

    parts = []
    async for part in provider.stream(_req()):
        parts.append(part)

    assert "".join(parts) == "Hello"
    assert provider._last_stream_usage is not None
    assert provider._last_stream_usage.prompt_tokens == 12
    assert provider._last_stream_usage.completion_tokens == 2
    assert provider._last_stream_usage.total_tokens == 14


class _GemChunk:
    def __init__(self, text, um=None):
        self.text = text
        self.usage_metadata = um


class _GemUsage:
    def __init__(self, prompt, candidates, total):
        self.prompt_token_count = prompt
        self.candidates_token_count = candidates
        self.total_token_count = total


class _GemModels:
    async def generate_content_stream(self, **_kw):
        async def gen():
            yield _GemChunk("Hi")
            yield _GemChunk(" there", um=_GemUsage(9, 6, 15))

        return gen()


class _GemAio:
    models = _GemModels()


class _GemClient:
    aio = _GemAio()


async def test_gemini_stream_captures_final_usage():
    # Bypass the real client constructor (aiohttp SSL quirk in this env) —
    # we only exercise the stream loop against the fake client.
    provider = GeminiProvider.__new__(GeminiProvider)
    provider._client = _GemClient()

    parts = []
    async for part in provider.stream(_req()):
        parts.append(part)

    assert "".join(parts) == "Hi there"
    assert provider._last_stream_usage is not None
    assert provider._last_stream_usage.prompt_tokens == 9
    assert provider._last_stream_usage.completion_tokens == 6
    assert provider._last_stream_usage.total_tokens == 15

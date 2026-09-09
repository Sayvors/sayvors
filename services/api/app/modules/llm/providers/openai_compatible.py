from typing import AsyncIterator

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionChunk

from .base import LLMProvider, LLMMessage, LLMRequest, LLMResponse, LLMUsage, ProviderError

PROVIDER_BASE_URLS: dict[str, str] = {
    "openai": "https://api.openai.com/v1",
    "grok": "https://api.x.ai/v1",
    "kimi": "https://api.moonshot.cn/v1",
    "deepseek": "https://api.deepseek.com/v1",
    "groq": "https://api.groq.com/openai/v1",
    "ollama": "http://localhost:11434/v1",
}


class OpenAICompatibleProvider(LLMProvider):
    def __init__(self, provider: str, api_key: str, base_url: str | None = None):
        self._provider = provider
        resolved_url = base_url or PROVIDER_BASE_URLS.get(provider, "https://api.openai.com/v1")
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=resolved_url,
            timeout=120.0,
        )

    def name(self) -> str:
        return self._provider

    def _build_messages(self, req: LLMRequest) -> list[dict[str, str]]:
        messages: list[dict[str, str]] = []
        if req.system_prompt:
            messages.append({"role": "system", "content": req.system_prompt})
        for m in req.messages:
            messages.append({"role": m.role, "content": m.content})
        return messages

    async def complete(self, req: LLMRequest) -> LLMResponse:
        try:
            response = await self._client.chat.completions.create(
                model=req.model,
                messages=self._build_messages(req),
                temperature=req.temperature,
                max_tokens=req.max_tokens,
                stream=False,
            )
            choice = response.choices[0]
            usage = LLMUsage(
                prompt_tokens=response.usage.prompt_tokens if response.usage else 0,
                completion_tokens=response.usage.completion_tokens if response.usage else 0,
                total_tokens=response.usage.total_tokens if response.usage else 0,
            )
            return LLMResponse(
                content=choice.message.content or "",
                provider=self._provider,
                model=response.model,
                usage=usage,
                finish_reason=choice.finish_reason or "stop",
            )
        except Exception as e:
            status = self._map_error(e)
            raise ProviderError(self._provider, str(e), status)

    async def stream(self, req: LLMRequest) -> AsyncIterator[str]:
        try:
            response = await self._client.chat.completions.create(
                model=req.model,
                messages=self._build_messages(req),
                temperature=req.temperature,
                max_tokens=req.max_tokens,
                stream=True,
            )
            async for chunk in response:
                delta = self._extract_delta(chunk)
                if delta:
                    yield delta
        except Exception as e:
            status = self._map_error(e)
            raise ProviderError(self._provider, str(e), status)

    @staticmethod
    def _extract_delta(chunk: ChatCompletionChunk) -> str | None:
        if chunk.choices and chunk.choices[0].delta:
            return chunk.choices[0].delta.content
        return None

    @staticmethod
    def _map_error(e: Exception) -> int:
        msg = str(e).lower()
        if "authentication" in msg or "api key" in msg or "invalid_api_key" in msg:
            return 502
        if "rate" in msg and "limit" in msg:
            return 429
        if "timeout" in msg:
            return 504
        if "does not exist" in msg or "model" in msg:
            return 502
        return 502

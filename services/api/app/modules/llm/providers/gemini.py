from typing import AsyncIterator

from google import genai
from google.genai.types import Content, GenerateContentResponse, Part

from .base import LLMProvider, LLMMessage, LLMRequest, LLMResponse, LLMUsage, ProviderError


class GeminiProvider(LLMProvider):
    def __init__(self, api_key: str):
        self._client = genai.Client(api_key=api_key)

    def name(self) -> str:
        return "gemini"

    def _build_contents(self, req: LLMRequest) -> list[Content]:
        contents: list[Content] = []
        for m in req.messages:
            role = "model" if m.role == "assistant" else "user"
            contents.append(Content(
                role=role,
                parts=[Part.from_text(text=m.content)],
            ))
        return contents

    def _build_config(self, req: LLMRequest) -> dict:
        config: dict = {
            "temperature": req.temperature,
            "max_output_tokens": req.max_tokens,
        }
        if req.system_prompt:
            config["system_instruction"] = req.system_prompt
        return config

    async def complete(self, req: LLMRequest) -> LLMResponse:
        try:
            response: GenerateContentResponse = await self._client.aio.models.generate_content(
                model=req.model,
                contents=self._build_contents(req),
                config=self._build_config(req),
            )
            text = response.text or ""
            usage_meta = response.usage_metadata
            usage = LLMUsage(
                prompt_tokens=getattr(usage_meta, "prompt_token_count", 0) or 0,
                completion_tokens=getattr(usage_meta, "candidates_token_count", 0) or 0,
                total_tokens=getattr(usage_meta, "total_token_count", 0) or 0,
            )
            return LLMResponse(
                content=text,
                provider="gemini",
                model=req.model,
                usage=usage,
                finish_reason="stop",
            )
        except Exception as e:
            status = self._map_error(e)
            raise ProviderError("gemini", str(e), status)

    async def stream(self, req: LLMRequest) -> AsyncIterator[str]:
        try:
            async for chunk in await self._client.aio.models.generate_content_stream(
                model=req.model,
                contents=self._build_contents(req),
                config=self._build_config(req),
            ):
                if chunk.text:
                    yield chunk.text
        except Exception as e:
            status = self._map_error(e)
            raise ProviderError("gemini", str(e), status)

    @staticmethod
    def _map_error(e: Exception) -> int:
        msg = str(e).lower()
        if "api key" in msg or "authentication" in msg or "permission" in msg:
            return 502
        if "quota" in msg or "rate" in msg:
            return 429
        if "timeout" in msg:
            return 504
        if "not found" in msg or "does not exist" in msg:
            return 502
        return 502

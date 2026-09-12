from typing import AsyncIterator

from google import genai
from google.genai.types import (
    Content,
    FunctionDeclaration,
    GenerateContentResponse,
    Part,
    Tool,
)

from .base import (
    LLMProvider,
    LLMMessage,
    LLMRequest,
    LLMResponse,
    LLMUsage,
    ProviderError,
    ToolCall,
    ToolDefinition,
)


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
        if req.tools:
            config["tools"] = [Tool(function_declarations=[
                self._to_declaration(t) for t in req.tools
            ])]
        return config

    @staticmethod
    def _to_declaration(tool: ToolDefinition) -> FunctionDeclaration:
        properties = {}
        for name, param in tool.parameters.items():
            schema: dict = {"type": param.type.upper(), "description": param.description}
            if param.enum:
                schema["enum"] = param.enum
            if param.items_type:
                schema["items"] = {"type": param.items_type.upper()}
            properties[name] = schema
        return FunctionDeclaration(
            name=tool.name,
            description=tool.description,
            parameters={
                "type": "OBJECT",
                "properties": properties,
                "required": tool.required,
            },
        )

    @staticmethod
    def _parse_calls(response: GenerateContentResponse) -> tuple[str, list[ToolCall]]:
        text_parts: list[str] = []
        calls: list[ToolCall] = []
        for candidate in response.candidates or []:
            content = getattr(candidate, "content", None)
            for part in (getattr(content, "parts", None) or []):
                fn_call = getattr(part, "function_call", None)
                if fn_call is not None:
                    args = getattr(fn_call, "args", {}) or {}
                    calls.append(ToolCall(
                        name=getattr(fn_call, "name", ""),
                        arguments=dict(args),
                        call_id=getattr(fn_call, "id", "") or "",
                    ))
                elif getattr(part, "text", None):
                    text_parts.append(part.text)
        return "".join(text_parts), calls

    async def _complete(self, req: LLMRequest) -> LLMResponse:
        try:
            response: GenerateContentResponse = await self._client.aio.models.generate_content(
                model=req.model,
                contents=self._build_contents(req),
                config=self._build_config(req),
            )
            text, calls = self._parse_calls(response)
            if not text:
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
                finish_reason="tool_calls" if calls else "stop",
                tool_calls=calls,
            )
        except ProviderError:
            raise
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

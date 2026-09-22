from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import AsyncIterator


class ProviderError(Exception):
    def __init__(self, provider: str, message: str, status_code: int = 502):
        self.provider = provider
        self.message = message
        self.status_code = status_code
        super().__init__(f"{provider}: {message}")


@dataclass
class LLMMessage:
    role: str
    content: str


@dataclass
class ToolParameter:
    """One JSON-schema property of a tool's input object."""

    type: str  # "string" | "integer" | "number" | "boolean" | "array"
    description: str = ""
    enum: list[str] | None = None
    items_type: str | None = None  # for type == "array"


@dataclass
class ToolDefinition:
    """Provider-agnostic function-calling tool."""

    name: str
    description: str
    parameters: dict[str, ToolParameter] = field(default_factory=dict)
    required: list[str] = field(default_factory=list)


@dataclass
class ToolCall:
    name: str
    arguments: dict
    call_id: str = ""


@dataclass
class LLMUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class LLMRequest:
    model: str  # provider-specific model name e.g. "gpt-4o"
    messages: list[LLMMessage] = field(default_factory=list)
    system_prompt: str | None = None
    temperature: float = 0.7
    max_tokens: int = 1000
    stream: bool = False
    tools: list[ToolDefinition] = field(default_factory=list)
    # Metering context (optional — recorded per call, never affects generation).
    tenant_id: str | None = None
    model_id: str | None = None  # catalog id e.g. "groq:oss-120b"
    purpose: str | None = None  # e.g. "review_engine.generate"
    channel_id: str | None = None


@dataclass
class LLMResponse:
    content: str
    provider: str
    model: str  # actual model name returned by provider
    usage: LLMUsage = field(default_factory=LLMUsage)
    finish_reason: str = "stop"
    tool_calls: list[ToolCall] = field(default_factory=list)


class LLMProvider(ABC):
    async def complete(self, req: LLMRequest) -> LLMResponse:
        """Timed template: runs _complete, records metering, re-raises errors.

        D1 enforcement: when the request carries a tenant_id, a flat AI
        credit reservation is taken BEFORE the provider is called (402 when
        the wallet is empty) and settled to the real token cost afterwards.
        Metering never blocks or breaks generation — recording is
        fire-and-forget with its own session.
        """
        import time

        reserved = 0
        if req.tenant_id:
            from ...billing.budget import BudgetExhausted, reserve

            try:
                reserved = await reserve(req.tenant_id) or 0
            except BudgetExhausted as e:
                from ..usage import record_usage_event

                record_usage_event(req, None, 0, status="error", error=str(e)[:300])
                raise ProviderError("budget", str(e), 402) from e

        t0 = time.monotonic()
        try:
            resp = await self._complete(req)
        except Exception as e:
            from ..usage import record_usage_event

            record_usage_event(
                req, None, int((time.monotonic() - t0) * 1000),
                status="error", error=str(e)[:300],
            )
            if req.tenant_id and reserved:
                from ...billing.budget import settle

                await settle(req.tenant_id, reserved, 0)
            raise
        from ..usage import record_usage_event

        record_usage_event(req, resp, int((time.monotonic() - t0) * 1000))
        if req.tenant_id and reserved:
            from ...billing.budget import cost_cents, settle

            usage = resp.usage or LLMUsage()
            actual = cost_cents(req.model_id or req.model,
                                usage.prompt_tokens, usage.completion_tokens)
            await settle(req.tenant_id, reserved, actual)
        return resp

    @abstractmethod
    async def _complete(self, req: LLMRequest) -> LLMResponse:
        """Send a completion request to the provider."""
        ...

    @abstractmethod
    async def stream(self, req: LLMRequest) -> AsyncIterator[str]:
        """Stream tokens from the provider."""
        ...

    @abstractmethod
    def name(self) -> str:
        ...

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


@dataclass
class LLMResponse:
    content: str
    provider: str
    model: str  # actual model name returned by provider
    usage: LLMUsage = field(default_factory=LLMUsage)
    finish_reason: str = "stop"
    tool_calls: list[ToolCall] = field(default_factory=list)


class LLMProvider(ABC):
    @abstractmethod
    async def complete(self, req: LLMRequest) -> LLMResponse:
        """Send a completion request to the provider."""
        ...

    @abstractmethod
    async def stream(self, req: LLMRequest) -> AsyncIterator[str]:
        """Stream tokens from the provider."""
        ...

    @abstractmethod
    def name(self) -> str:
        ...

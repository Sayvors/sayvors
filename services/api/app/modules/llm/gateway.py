"""The public LLM gateway.

Every model call in the product goes through this module. It owns:

* **resolution** — catalog model id -> provider key + provider-specific name
* **provider selection** — one shared provider instance per provider
* **budget** — ``complete`` pre-authorizes through ``LLMProvider.complete``
  and settles the real token cost; ``stream`` reserves around the provider
  iterator and settles an estimated cost (streams report no usage). A
  ``tenant_id=None`` call is a system call and is never gated
* **metering** — one ``llm_usage_events`` row per call, streamed ones included

Feature modules must not import ``llm.providers`` directly. A hand-built
``provider.complete(LLMRequest(...))`` silently loses the required purpose,
the budget gate or the usage row — exactly the class of bug this module
exists to make impossible.

Resolution delegates to the LLM service so the admin's custom-model overlay
and the existing test seams keep working; it is imported lazily to avoid a
module cycle (``service`` imports this module for its own chat calls).
"""

import time
from collections.abc import AsyncIterator
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from ..billing.budget import (
    BudgetExhausted,
    BudgetUnavailable,
    cost_cents,
    reserve,
    settle,
)
from .providers import registry
from .providers.base import (
    LLMMessage,
    LLMRequest,
    LLMResponse,
    LLMUsage,
    ProviderError,
    ToolCall,
    ToolDefinition,
    ToolParameter,
    merge_consecutive,
)
from .usage import record_usage_event

__all__ = [
    "LLMMessage",
    "LLMResponse",
    "LLMUsage",
    "ProviderError",
    "ResolvedModel",
    "ToolCall",
    "ToolDefinition",
    "ToolParameter",
    "complete",
    "ensure_usable",
    "merge_consecutive",
    "resolve_model",
    "resolve_tenant_model",
    "stream",
]

# Streamed completions do not return token usage. Estimate with the common
# 4-characters-per-token heuristic so the dashboard and the cost ledger still
# see the call; the purpose column makes the estimate attributable.
_STREAM_CHARS_PER_TOKEN = 4


@dataclass(frozen=True)
class ResolvedModel:
    """A catalog model id mapped to the provider's own model name."""

    model_id: str
    api_model: str
    provider: str


def resolve_model(model_id: str) -> ResolvedModel:
    """Resolve a catalog model id (``groq:oss-120b``) to its API model."""
    from .service import _resolve_model

    api_model, provider = _resolve_model(model_id)
    return ResolvedModel(model_id=model_id, api_model=api_model, provider=provider)


def ensure_usable(model_id: str) -> ResolvedModel:
    """Resolve a model and fail now when its provider cannot be used.

    Callers that fall back across candidates (the databank agent) use this to
    skip disabled providers and missing keys before spending a request.
    """
    resolved = resolve_model(model_id)
    registry.get_provider_for_model(model_id)
    return resolved


async def resolve_tenant_model(db: AsyncSession, preferred: str | None = None) -> str:
    """The single model id a tenant may generate with.

    Raises ``ValueError`` when the admin has enabled nothing — there are no
    silent defaults or fallbacks.
    """
    from .service import resolve_tenant_model as _resolve

    # Preserve the one-argument call shape: a test double (and any caller)
    # that patches the service function may not accept ``preferred``.
    if preferred is None:
        return await _resolve(db)
    return await _resolve(db, preferred)


def _build_request(
    *,
    model_id: str,
    resolved: ResolvedModel,
    messages: list[LLMMessage],
    purpose: str,
    system_prompt: str | None,
    temperature: float,
    max_tokens: int,
    stream: bool,
    tools: list[ToolDefinition] | None,
    tenant_id: str | None,
    channel_id: str | None,
) -> LLMRequest:
    return LLMRequest(
        model=resolved.api_model,
        messages=messages,
        system_prompt=system_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
        stream=stream,
        tools=tools or [],
        tenant_id=tenant_id,
        model_id=model_id,
        purpose=purpose,
        channel_id=channel_id,
    )


async def complete(
    *,
    model: str,
    messages: list[LLMMessage],
    purpose: str,
    system_prompt: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 1000,
    tools: list[ToolDefinition] | None = None,
    tenant_id: str | None = None,
    channel_id: str | None = None,
) -> LLMResponse:
    """One completion through the budgeted, metered path.

    ``purpose`` has no default: an LLM call nobody can attribute is a cost
    nobody budgeted for, so every caller must name its use.
    """
    await registry.ensure_provider_keys_fresh()
    # Plan entitlement: AI replies must be enabled for this tenant.
    if tenant_id:
        from ..billing.entitlements import check_feature
        await check_feature(tenant_id, "ai_replies")
    resolved = resolve_model(model)
    provider = registry.get_provider_for_model(model)
    req = _build_request(
        model_id=model,
        resolved=resolved,
        messages=messages,
        purpose=purpose,
        system_prompt=system_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
        stream=False,
        tools=tools,
        tenant_id=tenant_id,
        channel_id=channel_id,
    )
    return await provider.complete(req)


async def stream(
    *,
    model: str,
    messages: list[LLMMessage],
    purpose: str,
    system_prompt: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 1000,
    tenant_id: str | None = None,
    channel_id: str | None = None,
) -> AsyncIterator[str]:
    """Yield a streamed completion through the budgeted, metered path.

    Providers return token usage only for non-streamed completions, so this
    path estimates: prompt tokens from the characters sent, completion tokens
    from the characters streamed. The reservation is settled exactly once, in
    ``finally``, so a provider failure refunds it and a client disconnect still
    charges for what was delivered.
    """
    await registry.ensure_provider_keys_fresh()
    # Plan entitlement: AI replies must be enabled for this tenant.
    if tenant_id:
        from ..billing.entitlements import check_feature
        await check_feature(tenant_id, "ai_replies")
    resolved = resolve_model(model)
    provider = registry.get_provider_for_model(model)
    req = _build_request(
        model_id=model,
        resolved=resolved,
        messages=messages,
        purpose=purpose,
        system_prompt=system_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
        stream=True,
        tools=None,
        tenant_id=tenant_id,
        channel_id=channel_id,
    )

    reservation = None
    if tenant_id:
        try:
            reservation = await reserve(tenant_id, model_id=model, purpose=purpose)
        except (BudgetExhausted, BudgetUnavailable) as e:
            raise ProviderError("budget", str(e), e.status_code) from e

    prompt_tokens = (
        len(system_prompt or "")
        + sum(len(m.content or "") for m in messages)
    ) // _STREAM_CHARS_PER_TOKEN

    parts: list[str] = []
    started = time.monotonic()
    completed = False
    failure: Exception | None = None
    try:
        async for chunk in provider.stream(req):
            if not chunk:
                continue
            parts.append(chunk)
            yield chunk
        completed = True
    except Exception as e:  # re-raised after the usage row and refund
        failure = e
        raise
    finally:
        latency_ms = int((time.monotonic() - started) * 1000)
        text = "".join(parts)
        completion_tokens = (
            max(1, len(text) // _STREAM_CHARS_PER_TOKEN) if text else 0
        )
        from ..billing import pricing as _pricing

        await _pricing.ensure_fresh()
        actual = (
            0
            if failure is not None
            else cost_cents(model, prompt_tokens, completion_tokens)
        )
        if reservation is not None:
            await settle(
                reservation,
                actual,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )
        ledger_id = reservation.id if reservation is not None else None
        if failure is not None:
            record_usage_event(
                req,
                None,
                latency_ms,
                status="error",
                error=str(failure)[:300],
                cost_cents=0,
                ledger_id=ledger_id,
            )
        elif completed or text:
            record_usage_event(
                req,
                LLMResponse(
                    content=text,
                    provider=resolved.provider,
                    model=resolved.api_model,
                    usage=LLMUsage(
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        total_tokens=prompt_tokens + completion_tokens,
                    ),
                    finish_reason="stop" if completed else "cancelled",
                ),
                latency_ms,
                status="ok" if completed else "cancelled",
                cost_cents=actual,
                ledger_id=ledger_id,
            )

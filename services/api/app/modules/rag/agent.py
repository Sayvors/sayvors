"""Agentic RAG: the tenant's model thinks, calls retrieval tools, then answers.

Loop (max N steps): model output -> tool calls -> observations -> model.
The reasoning model is the caller's / the tenant's configured model (Gemini
only as a last resort), so databank search works on whichever provider the
tenant actually has configured.
Tenant database rows live only inside this request: tools return row
*content* for the prompt, but nothing here persists rows to our tables,
disk, logs, or Kafka. Server logs record tool names + row counts only.
"""

import inspect
import json
import logging
import time
from typing import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from ..llm.providers.base import LLMMessage, LLMRequest, LLMResponse, ProviderError
from ..users.models import User
from .service import get_databank
from .tools import TOOL_RUNNERS, ToolContext, tool_definitions

logger = logging.getLogger(__name__)

AGENT_MODEL = "gemini-3.6-flash"
MAX_STEPS = 6
MAX_OBSERVATION_CHARS = 4000

# Returned when retrieval found nothing usable. Callers compare against this
# so an honest "found nothing" is never reported as a grounded answer.
NO_EVIDENCE_ANSWER = (
    "I couldn't find enough evidence to answer that. Try different wording, "
    "or add more sources to this databank."
)

SYSTEM_PROMPT = """You are the retrieval agent for a business knowledge base.
Answer the user's question using ONLY the evidence your tools return.

Rules:
- First decide what you need: documents (vector_search / keyword_search),
  surrounding context (read_around), full texts (get_document), or live
  database rows (db_schema then db_query).
- Prefer db_query for questions about current records (orders, users,
  inventory, counts). Prefer vector_search for meaning questions and
  keyword_search for exact terms (SKUs, names, codes).
- Never invent rows, numbers, or facts. If the tools return nothing useful,
  say so plainly and suggest what the owner could add.
- Reply in the same language as the user's question.
- Keep the final answer tight; mention whether each fact came from live
  data or stored documents."""


def _filter_args(runner, args: dict) -> dict:
    try:
        params = inspect.signature(runner).parameters
    except (TypeError, ValueError):
        return {}
    return {k: v for k, v in (args or {}).items() if k in params and k != "ctx"}


def _redact(args: dict) -> dict:
    redacted = dict(args or {})
    for key in ("password", "token", "secret"):
        if key in redacted:
            redacted[key] = "***"
    if "sql" in redacted and isinstance(redacted["sql"], str) and len(redacted["sql"]) > 300:
        redacted["sql"] = redacted["sql"][:300] + "…"
    return redacted


async def _resolve_agent_model(db: AsyncSession, preferred: str | None = None) -> tuple:
    """Pick the model that reasons over the databank tools.

    Was hardcoded to Gemini, which meant databank search failed for any
    tenant whose AI ran on another provider (e.g. Qwen on Groq) even though
    their model was perfectly capable of tool calling. Now: the caller's
    model if given, else the tenant's configured model, else Gemini as the
    last resort.

    Returns (provider, model_id, api_model).
    """
    from ..llm.providers.registry import get_provider_for_model
    from ..llm.service import _resolve_model as resolve_api_model, resolve_tenant_model

    candidates: list[str] = []
    if preferred:
        candidates.append(preferred)
    try:
        candidates.append(await resolve_tenant_model(db))
    except ValueError:
        pass
    candidates.append(AGENT_MODEL)

    seen: set[str] = set()
    last_error: Exception | None = None
    for model_id in candidates:
        if model_id in seen:
            continue
        seen.add(model_id)
        try:
            provider = get_provider_for_model(model_id)
        except Exception as e:  # provider disabled / key missing
            last_error = e
            continue
        api_model, _ = resolve_api_model(model_id)
        return provider, model_id, api_model
    raise last_error or ProviderError("llm", "No usable model for databank search", 503)


async def ask_question(
    databank_id: str,
    question: str,
    user: User,
    db: AsyncSession,
    top_k: int = 5,
    max_steps: int = MAX_STEPS,
    on_tool: "Callable[[str, dict], None] | None" = None,
    model: str | None = None,
) -> dict:
    bank = await get_databank(databank_id, user, db)
    if not bank:
        raise ValueError("Databank not found")

    provider, model_id, api_model = await _resolve_agent_model(db, model)
    ctx = ToolContext(databank_id=databank_id, user_id=user.id, db=db)
    tools = tool_definitions()

    messages = [LLMMessage(role="user", content=question)]
    trace: list[dict] = []
    seen_passages: list[dict] = []
    steps_used = 0
    answer = ""

    max_steps = max(1, min(int(max_steps or MAX_STEPS), 10))
    for step in range(max_steps):
        steps_used = step + 1
        resp: LLMResponse = await provider.complete(LLMRequest(
            model=api_model,
            messages=list(messages),
            system_prompt=SYSTEM_PROMPT,
            temperature=0.2,
            max_tokens=2048,
            tools=tools,
            tenant_id=user.id,
            model_id=model_id,
            purpose="databank.ask",
        ))
        if not resp.tool_calls:
            answer = resp.content.strip()
            trace.append({"step": steps_used, "thought": resp.content[:500],
                          "tool": None, "args": {}, "ms": 0,
                          "observation": "final answer"})
            break

        observations: list[str] = []
        for call in resp.tool_calls:
            runner = TOOL_RUNNERS.get(call.name)
            started = time.monotonic()
            if runner is None:
                obs: dict = {"error": f"unknown tool: {call.name}"}
            else:
                try:
                    obs = await runner(ctx, **_filter_args(runner, call.arguments))
                except Exception as e:
                    logger.warning("Agent tool %s failed: %s", call.name, e)
                    obs = {"error": f"{call.name} failed"}
            ms = int((time.monotonic() - started) * 1000)
            for passage in obs.get("passages", []):
                seen_passages.append(passage)
            if on_tool is not None:
                # Progress hook for streaming UIs (e.g. Ask Sayvors). Reports the
                # tool name and observation size only — never row content.
                try:
                    on_tool(call.name, {
                        "passages": len(obs.get("passages", [])),
                        "ms": ms,
                    })
                except Exception:  # progress must never break retrieval
                    logger.debug("on_tool callback failed", exc_info=True)
            summary = json.dumps(obs)[:MAX_OBSERVATION_CHARS]
            trace.append({"step": steps_used,
                          "thought": (resp.content or "")[:500],
                          "tool": call.name,
                          "args": _redact(call.arguments),
                          "ms": ms,
                          "observation": summary[:500]})
            observations.append(f"Tool {call.name} returned:\n{summary}")
            logger.info("agent step %d tool=%s ms=%d passages=%d",
                        steps_used, call.name, ms, len(obs.get("passages", [])))

        messages.append(LLMMessage(
            role="assistant",
            content=(resp.content or "") + f"\n[called {len(resp.tool_calls)} tool(s)]",
        ))
        messages.append(LLMMessage(role="user", content="\n\n".join(observations)))
    else:
        # Step budget exhausted: one final no-tools pass to synthesize.
        resp = await provider.complete(LLMRequest(
            model=api_model,
            messages=list(messages) + [LLMMessage(
                role="user",
                content="Answer now with the evidence gathered so far, or say what is missing.")],
            system_prompt=SYSTEM_PROMPT,
            temperature=0.2,
            max_tokens=2048,
            tenant_id=user.id,
            model_id=model_id,
            purpose="databank.ask",
        ))
        answer = resp.content.strip()

    if not answer:
        answer = NO_EVIDENCE_ANSWER

    citations: list[dict] = []
    seen_origins: set[str] = set()
    for p in seen_passages:
        origin = str(p.get("origin", "unknown"))
        if origin in seen_origins:
            continue
        seen_origins.add(origin)
        kind = "live" if origin.startswith("live:") else "snapshot"
        citations.append({"source": origin, "kind": kind,
                          "detail": str(p.get("content", ""))[:200]})

    return {"answer": answer, "citations": citations, "trace": trace,
            "steps_used": steps_used, "model": model_id}

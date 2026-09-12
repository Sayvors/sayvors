"""Agentic RAG: Gemini thinks, calls retrieval tools, then answers.

Loop (max N steps): model output -> tool calls -> observations -> model.
Tenant database rows live only inside this request: tools return row
*content* for the prompt, but nothing here persists rows to our tables,
disk, logs, or Kafka. Server logs record tool names + row counts only.
"""

import inspect
import json
import logging
import time

from sqlalchemy.ext.asyncio import AsyncSession

from ..llm.providers.base import LLMMessage, LLMRequest, LLMResponse, ProviderError
from ..llm.providers.registry import get_provider
from ..users.models import User
from .service import get_databank
from .tools import TOOL_RUNNERS, ToolContext, tool_definitions

logger = logging.getLogger(__name__)

AGENT_MODEL = "gemini-3.6-flash"
MAX_STEPS = 6
MAX_OBSERVATION_CHARS = 4000

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


async def ask_question(
    databank_id: str,
    question: str,
    user: User,
    db: AsyncSession,
    top_k: int = 5,
    max_steps: int = MAX_STEPS,
) -> dict:
    bank = await get_databank(databank_id, user, db)
    if not bank:
        raise ValueError("Databank not found")

    provider = get_provider("gemini")  # 503 when no key is stored in admin
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
            model=AGENT_MODEL,
            messages=list(messages),
            system_prompt=SYSTEM_PROMPT,
            temperature=0.2,
            max_tokens=2048,
            tools=tools,
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
            model=AGENT_MODEL,
            messages=list(messages) + [LLMMessage(
                role="user",
                content="Answer now with the evidence gathered so far, or say what is missing.")],
            system_prompt=SYSTEM_PROMPT,
            temperature=0.2,
            max_tokens=2048,
        ))
        answer = resp.content.strip()

    if not answer:
        answer = "I couldn't find enough evidence to answer that. Try different wording, or add more sources to this databank."

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
            "steps_used": steps_used, "model": AGENT_MODEL}

"""Response renderer: one logical AI reply -> the messages WhatsApp receives.

The agent (history, business card, LLM call, goal checks) is untouched — it
produces ONE logical response exactly as before. Only delivery differs by
tenant style:

  "concise" — the response goes out as a single WhatsApp message (today's
              behaviour, byte for byte).
  "human"   — a small second LLM pass may split the response into 1..N short
              natural messages the way a person types. The AI decides
              intelligently per response; there is no mechanical word or
              sentence chopping. Anything that goes wrong falls back to the
              single-message behaviour, so a renderer hiccup can never eat a
              reply — it can only fail back to concise.
"""
import json
import logging

from .chat_voice import clean_reply

logger = logging.getLogger(__name__)

# Extensible string enum: new styles join the tuple (and the API pattern)
# without a data migration.
RESPONSE_STYLES = ("concise", "human")
DEFAULT_RESPONSE_STYLE = "concise"

# A person doesn't fire 6 bubbles back to back; past this the split has
# stopped being human and started being noise.
_MAX_HUMAN_MESSAGES = 4

_SPLIT_SYSTEM_PROMPT = (
    "You prepare replies for WhatsApp on behalf of a small business. You get "
    "one finished reply and decide how a human would type it into the chat "
    "app.\n"
    "Return ONLY a JSON array of 1 to 4 strings — the messages to send, in "
    "order.\n"
    "Rules:\n"
    "- Split only where a person naturally would: a greeting, a new thought, "
    "a question, a short list. Most replies are fine as ONE message — return "
    "one element when so.\n"
    "- You may LIGHTLY tighten the wording for chat: use contractions "
    "('it's', 'we'll'), drop formal openers ('Dear customer', 'Hello "
    "there') and filler ('kindly', 'please note'). This is touch-up only.\n"
    "- Never change facts, numbers, names, prices, promises, dates or the "
    "meaning. Never add information that is not in the reply. When in "
    "doubt, keep the original wording.\n"
    "- No message may be a bare fragment like 'ok' or a single word unless "
    "the reply itself contains it.\n"
    "- Plain text only (WhatsApp): no markdown, no numbering the split.\n"
    "- Never use em dashes or en dashes; use commas or full stops instead."
)


def normalize_response_style(value: str | None) -> str:
    """The stored style as the renderer understands it.

    Never raises: a NULL column, a pre-migration row or a bad hand-edit all
    fall back to the default instead of dropping the tenant's reply.
    """
    return value if value in RESPONSE_STYLES else DEFAULT_RESPONSE_STYLE


def concise_renderer(response: str, lint_enabled: bool = True) -> list[str]:
    """One clear message per response — the historical behaviour.

    The deterministic linter runs here too, so every style gets the same
    machine-tell cleanup before it reaches the customer. ``lint_enabled``
    is the per-tenant rollout flag (false = raw text, for controlled
    rollback).
    """
    text = clean_reply(response) if lint_enabled else (response or "").strip()
    return [text] if text else []


async def human_renderer(
    response: str, tenant_id: str, db, lint_enabled: bool = True
) -> list[str]:
    """Split into 1..N natural messages; ALWAYS falls back to [response]."""
    text = clean_reply(response) if lint_enabled else (response or "").strip()
    if not text:
        return []
    try:
        raw = await _ask_split(tenant_id, db, text)
        messages = _parse_message_list(raw)
    except Exception as e:
        logger.info(
            "Human-style rendering fell back to single message tenant=%s: "
            "%s: %s", tenant_id, type(e).__name__, str(e)[:150],
        )
        return [text]
    if not messages or _looks_lossy(text, messages):
        return [text]
    return messages


async def render_response(
    style: str, response: str, tenant_id: str, db,
    lint_enabled: bool = True,
) -> list[str]:
    """The spec's router: style in, sendable messages out. The only place
    the tenant style is consulted — agent reasoning never sees it.

    ``lint_enabled`` is the per-tenant rollout knob for the deterministic
    linter (Phase 2); false bypasses it entirely.
    """
    if normalize_response_style(style) == "human":
        return await human_renderer(response, tenant_id, db, lint_enabled)
    return concise_renderer(response, lint_enabled)


async def _ask_split(tenant_id: str, db, response_text: str) -> str:
    """One small LLM pass returning the JSON array (or raising)."""
    from ...llm.gateway import LLMMessage, complete, resolve_tenant_model

    model_id = await resolve_tenant_model(db)  # ValueError when nothing enabled
    resp = await complete(
        model=model_id,
        # Single user turn — no consecutive same-role turns, so the qwen3
        # empty-completion hazard that hit the reply path can't occur here.
        messages=[LLMMessage(role="user", content=response_text)],
        system_prompt=_SPLIT_SYSTEM_PROMPT,
        temperature=0.2,
        max_tokens=500,
        tenant_id=tenant_id,
        purpose="whatsapp.render_style",
    )
    return (resp.content or "").strip()


def _parse_message_list(raw: str | None) -> list[str]:
    """Strings from the outermost JSON array; tolerant of prose around it."""
    if not raw:
        return []
    start, end = raw.find("["), raw.rfind("]")
    if start == -1 or end <= start:
        return []
    try:
        parsed = json.loads(raw[start:end + 1])
    except (ValueError, TypeError):
        return []
    if not isinstance(parsed, list):
        return []
    messages = [str(item).strip() for item in parsed if str(item or "").strip()]
    return messages[:_MAX_HUMAN_MESSAGES]


def _looks_lossy(original: str, messages: list[str]) -> bool:
    """True when the split dropped most of the reply's text — the model
    summarized instead of only moving boundaries, so we send the original
    instead of a shortened answer.

    Also flags suspicious growth (combined length far above the original):
    the edit tier may tighten, never expand — expansion means the model
    added content, which is a hallucination risk we refuse to send.
    """
    kept = sum(len(m) for m in messages)
    if kept < len(original) // 3:
        return True
    return kept > len(original) * 3 // 2

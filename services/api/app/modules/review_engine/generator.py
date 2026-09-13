"""Generate a review response using selected strategies + business context."""
import json
import logging
import time

from ..llm.providers.base import LLMMessage, LLMRequest, ProviderError
from ..llm.providers.registry import get_provider_for_model
from ..llm.service import _resolve_model
from .schemas import (
    ExtractedIssue,
    GeneratedResponse,
    ReviewAnalysis,
    StrategyMatch,
    ToolCall,
)

logger = logging.getLogger(__name__)


def _salvage_response_text(raw: str) -> str:
    """Extract a partial response_text from a truncated JSON wrapper.

    Handles: '{"response_text":"Thank you... We' → 'Thank you... We'
    Returns "" when nothing usable is present.
    """
    import re

    m = re.search(r'"response_text"\s*:\s*"(.*)', raw, re.DOTALL)
    if not m:
        return ""
    partial = m.group(1)
    # Unescape common sequences; drop a dangling trailing backslash.
    partial = partial.rstrip("\\").replace('\\"', '"').replace("\\n", " ").replace("\\\\", "\\")
    return partial.strip()

RESPONSE_SYSTEM_PROMPT = """You are a real person replying to a customer review — not an AI, not a corporation.

Given:
1. The customer review analysis
2. Selected response strategies with instructions
3. Business context (if available)
4. Channel policy
5. Brand voice guidelines

Write like a friendly human texting a neighbor. Simple, warm, everyday English.

LANGUAGE — SIMPLE & HUMAN (non-negotiable):
- Use short, simple words anyone would use. Grade 5 reading level.
- GOOD: thanks, thank you, glad, happy, sorry, great, good, nice, love, appreciate
- BANNED AI/corporate words — never use: wonderful, thrilled, delighted, elated, heartfelt, cherish, utmost, sincerely, gracious, esteemed, patronage, exquisite, phenomenal, outstanding, truly blessed
- BANNED phrases — never use: "wonderful feedback", "thrilled you enjoyed", "delighted to hear", "we're thrilled", "we're delighted", "heartfelt thanks", "utmost gratitude", "it was a pleasure serving you", "we cherish your feedback"
- Instead of "Thank you for your wonderful feedback. We're thrilled you enjoyed your visit!" write "Thanks for the kind words! Glad you had a good time."
- Use contractions: we're, you're, didn't, it's, thanks — not "we are", "you are"
- One idea per sentence. Short sentences. Max 15 words per sentence.
- Warm but not over-the-top. No exclamation spam (max one ! per reply, often none).
- Sound like ONE person, not a PR team.

Rules:
- Follow the selected strategies' instructions closely.
- The Hard Requirements section is binding — violating one fails validation.
- COMPRESS: multiple strategies per sentence. 5 strategies ≠ 5 sentences.
  E.g. acknowledge + apologize + address can be ONE sentence:
  "Sorry you waited 45 minutes for cold food — that's not ok."
- If the customer did not ask for products, alternatives, offers, or a
  return visit, do NOT pitch any. A complaint needs acknowledgment, apology,
  specifics, and a useful next step — nothing more.
- Address EVERY concrete complaint fact explicitly, with specifics from the review.
- BANNED unless stated in Business Context: staff training/retraining,
  refunds issued, discounts invented, investigations, manager will contact you,
  policy changes, personnel actions, operational overhauls, "never happen again".
  Attitudes are fine ("we take this seriously", "happy to help").
- BANNED corporate openers: "valuable feedback", "patronage",
  "exceptional experience", "sincerely appreciate your patronage",
  "remain committed", "please be advised". Sound like a real person.
- ZERO internal taxonomy in customer copy: no snake_case terms, no labels
  like product_dissatisfaction or service_quality, no strategy names.
  Say "didn't meet your expectations", never the classification name.
- Pricing concern ("too expensive") is NOT a billing error: never use
  refund/charge/invoice/payment-failure language for price opinions.
- If asked WHY and Business Context has no verified reason, say so plainly
  ("we don't have that detail here") or just acknowledge — never invent
  pricing rationale, ingredient stories, or process explanations.
- Product suggestions: only if Business Context lists a verified complementary product. Use its exact name. If a URL/link is in the Context, you may add it as " — see: https://..." in the same clause. If no link is in Context, do NOT invent one. Keep it to one brief clause, like "If you're curious, our Voice AI Pro pairs nicely — happy to share more if you want."
- Never invent links/URLs. Only share a link that appears verbatim in Business Context.
- Never leak strategy names or AI self-references into the reply.
- Do NOT invent facts, prices, discounts, refund amounts, or actions taken.
- Do NOT include phone numbers, emails, or personal information.
- Do NOT ask the reviewer to change their rating.
- Match the brand voice but keep it HUMAN and SIMPLE.
- Return ONLY a JSON object: {{"response_text": "...", "reasoning": "..."}}
- No markdown. No explanation outside the JSON.
- ALWAYS close the JSON object. Never stop mid-sentence.

EXAMPLES — copy this tone:
- 5★ "Loved the food!" → "Thanks so much! Glad you loved it — hope to see you again soon."
- 5★ no text → "Thanks for the 5 stars! Really appreciate it."
- 1★ "Waited 45 min, cold food, rude staff" → "Sorry about the long wait, cold food, and rude service — that's not ok. Thanks for telling us, we'll fix it."
- Pricing "Great but costly" → "Thanks for the honest note — glad you like the tool. We hear you on price and appreciate you sharing."
"""


async def generate_response(
    analysis: ReviewAnalysis,
    strategies: list[StrategyMatch],
    channel_policy: dict,
    brand_voice: dict,
    business_context: str | None,
    model: str,
    issues: list[ExtractedIssue] | None = None,
    requirements: list[str] | None = None,
    previous_issues: list[str] | None = None,
    tier: dict | None = None,
    tenant_id: str | None = None,
    channel_id: str | None = None,
) -> tuple[GeneratedResponse, dict]:
    """Generate a review response from analysis + strategies."""
    user_parts = []

    user_parts.append(f"## Review Analysis\n{json.dumps(analysis.model_dump(), indent=2)}")

    if tier:
        user_parts.append(
            f"## Length Target (binding)\n{tier['max_sentences']} sentences max, "
            f"~{tier['min_words']}-{tier['max_words']} words. "
            f"Compress all strategies into this budget — do NOT write one sentence per strategy."
        )

    strategy_section = "## Selected Strategies (ordered by priority)\n"
    for s in strategies:
        line = f"- **{s.name}** (priority {s.priority}): {s.reason}"
        if s.conditional and s.condition_note:
            line += f" [CONDITIONAL: {s.condition_note}]"
        strategy_section += line + "\n"
    user_parts.append(strategy_section)

    if issues:
        issue_lines = "\n".join(f"- {i.label}: {i.detail}" for i in issues)
        user_parts.append(f"## Concrete Complaint Facts (MUST address each explicitly)\n{issue_lines}")

    if requirements:
        req_lines = "\n".join(f"- {r}" for r in requirements)
        user_parts.append(f"## Hard Requirements (validation WILL reject the reply if violated)\n{req_lines}")

    if previous_issues:
        prev_lines = "\n".join(f"- {p}" for p in previous_issues)
        user_parts.append(
            f"## Previous Attempt Failed Validation\n{prev_lines}\n"
            f"Fix EVERY item above in this new attempt."
        )

    user_parts.append(f"## Channel Policy\n{json.dumps(channel_policy, indent=2)}")
    user_parts.append(f"## Brand Voice\n{json.dumps(brand_voice, indent=2)}")

    if business_context:
        user_parts.append(f"## Business Context\n{business_context}")

    user_msg = "\n\n".join(user_parts)

    provider = get_provider_for_model(model)
    api_model, _ = _resolve_model(model)

    t0 = time.monotonic()
    try:
        resp = await provider.complete(
            LLMRequest(
                model=api_model,
                messages=[LLMMessage(role="user", content=user_msg)],
                system_prompt=RESPONSE_SYSTEM_PROMPT,
                temperature=0.6,
                max_tokens=800,
                stream=False,
                tenant_id=tenant_id,
                model_id=model,
                purpose="review_engine.generate",
                channel_id=channel_id,
            )
        )
    except ProviderError as e:
        logger.error("Response generation failed on %s: %s", model, e)
        raise

    latency = int((time.monotonic() - t0) * 1000)
    raw = resp.content.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

    response_text = ""
    try:
        data = json.loads(raw)
        response_text = (data.get("response_text") or "").strip()
    except json.JSONDecodeError:
        # Truncated JSON wrapper (e.g. '{"response_text":"Thank... We') —
        # salvage the partial value instead of echoing the raw blob.
        salvaged = _salvage_response_text(raw)
        if salvaged:
            logger.warning("Salvaged partial response_text from truncated JSON (%d chars)", len(salvaged))
            response_text = salvaged
        elif raw and not raw.startswith("{"):
            logger.warning("Failed to parse response JSON, using raw: %s", raw[:200])
            response_text = raw

    if not response_text:
        raise ProviderError(model, "Model returned an empty response", 502)

    generated = GeneratedResponse(
        response_text=response_text,
        strategies_used=[s.strategy_id for s in strategies],
        tools_called=[],
    )

    usage = {
        "model": model,
        "tokens": resp.usage.total_tokens,
        "latency_ms": latency,
    }
    return generated, usage

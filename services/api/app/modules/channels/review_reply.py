"""Generate merchant replies to Google reviews via LLM (+ optional RAG grounding)."""
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from ..llm.providers.base import LLMMessage, LLMRequest, ProviderError
from ..llm.providers.registry import get_provider_for_model
from .models import AutoReplyConfig

logger = logging.getLogger(__name__)

# Google review-reply policy constraints baked into every prompt:
# no advertising, no links, no asking to change the review, no personal data.
SYSTEM_PROMPT_TEMPLATE = """You are the owner of a business replying to a Google review.
Write a public reply from the business to the reviewer.

Rules you MUST follow (Google review reply policy):
- Never include links, phone numbers, promotional offers or marketing.
- Never ask or hint for the reviewer to change or remove their rating.
- Do not include personal data of the reviewer or staff.
- Keep it short: 2-4 sentences, plain text only (no markdown, no emoji spam).

Tone: {tone}.
{rating_guidance}
{custom_block}
{context_block}
Write only the reply text — nothing else."""

POSITIVE_GUIDANCE = "This is a positive review: thank the reviewer warmly and mention something specific they praised if possible."
NEUTRAL_GUIDANCE = "This is a neutral review: thank the reviewer and invite constructive feedback."
NEGATIVE_GUIDANCE = "This is a negative review: acknowledge the specific complaint, apologise sincerely, and offer to make it right. Do not be defensive. Do not dispute their account."


def _rating_guidance(rating: int) -> str:
    if rating >= 4:
        return POSITIVE_GUIDANCE
    if rating == 3:
        return NEUTRAL_GUIDANCE
    return NEGATIVE_GUIDANCE


async def _build_context(config: AutoReplyConfig, review_text: str, db: AsyncSession) -> str:
    """Pull relevant chunks from the linked Databank (if any) for grounding."""
    if not config.databank_id or not review_text:
        return ""
    try:
        from ..rag.service import search as rag_search
        from ..rag.schemas import SearchRequest

        # `search()` is scoped by databank_id (its `user` param is unused);
        # databank ownership was validated when the config was linked.
        results, _degraded = await rag_search(
            config.databank_id,
            SearchRequest(query=review_text[:500], top_k=3),
            None,  # type: ignore[arg-type]
            db,
        )
        if results:
            chunks = "\n".join(f"- {r['content'][:300]}" for r in results)
            return "Useful facts about the business (from the merchant's Databank):\n" + chunks
    except Exception as e:
        logger.warning("RAG context unavailable for review reply: %s", e)
    return ""


async def generate_review_reply(
    config: AutoReplyConfig,
    rating: int,
    review_text: str | None,
    reviewer_name: str | None,
    db: AsyncSession,
) -> str:
    """Generate a public reply to a review using the channel's configured model/tone."""
    # Dev mock mode: canned, policy-safe replies — no LLM call.
    from ...config import settings as _settings
    if _settings.GOOGLE_REVIEWS_MOCK:
        name = reviewer_name.split(" ")[0] if reviewer_name else "there"
        if rating >= 4:
            return (
                f"Thank you so much, {name}! We're thrilled you had a great experience "
                f"with us — feedback like yours keeps our team motivated. We hope to see you again soon!"
            )
        if rating == 3:
            return (
                f"Thanks for the honest feedback, {name}. We're glad parts of your visit "
                f"worked well, and we'd love to hear what we could improve next time."
            )
        return (
            f"We're truly sorry about your experience, {name}. That's not the standard we "
            f"aim for. Please reach out to us directly so we can make this right."
        )

    context_block = await _build_context(config, review_text or "", db)

    custom_block = ""
    if getattr(config, "custom_instructions", None):
        custom_block = (
            "Additional instructions from the business owner (follow these closely "
            "as long as they don't conflict with the rules above):\n"
            f"{config.custom_instructions.strip()[:1000]}"
        )

    system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
        tone=config.tone,
        rating_guidance=_rating_guidance(rating),
        custom_block=custom_block,
        context_block=context_block,
    )

    review_desc = review_text.strip() if review_text and review_text.strip() else "(no written comment, star rating only)"
    user_msg = f"Review by {reviewer_name or 'an anonymous customer'} — {rating}/5 stars:\n\"{review_desc}\""

    provider = get_provider_for_model(config.model)
    from ..llm.service import _resolve_model
    api_model, _ = _resolve_model(config.model)

    req = LLMRequest(
        model=api_model,
        messages=[LLMMessage(role="user", content=user_msg)],
        system_prompt=system_prompt,
        temperature=0.6,
        max_tokens=300,
        stream=False,
    )
    try:
        resp = await provider.complete(req)
    except ProviderError:
        # Configured model unreachable (no key, 403, …) — one retry on Groq.
        if config.model == "groq:oss-120b":
            raise
        logger.warning("Reply model %s failed; retrying on groq:oss-120b", config.model)
        provider = get_provider_for_model("groq:oss-120b")
        api_model, _ = _resolve_model("groq:oss-120b")
        req.model = api_model
        resp = await provider.complete(req)
    reply = resp.content.strip()
    if not reply:
        raise ProviderError(config.model, "Empty reply generated", 502)
    return reply

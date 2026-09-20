"""Generate merchant replies to Google reviews via LLM (+ optional RAG grounding)."""
import logging
import re

from sqlalchemy.ext.asyncio import AsyncSession

from ...database import async_session as _async_session
from ..llm.providers.base import LLMMessage, LLMRequest, ProviderError
from ..llm.providers.registry import get_provider_for_model
from .models import AutoReplyConfig

logger = logging.getLogger(__name__)

# Arabic-script characters (also covers Urdu, Persian) — the reply language
# must match the review language (Arabic review → Arabic reply).
_ARABIC_SCRIPT = re.compile(r"[؀-ۿ]")


def _review_language(review_text: str | None) -> str | None:
    """'ar' when the review uses Arabic script; None otherwise (English default)."""
    if review_text and _ARABIC_SCRIPT.search(review_text):
        return "ar"
    return None


# Google review-reply policy constraints baked into every prompt:
# no advertising, no links, no asking to change the review, no personal data.
SYSTEM_PROMPT_TEMPLATE = """You are the owner of a business replying to a Google review.
Write a public reply from the business to the reviewer.

Rules you MUST follow (Google review reply policy):
- Never include links, phone numbers, promotional offers or marketing.
- Never ask or hint for the reviewer to change or remove their rating.
- Do not include personal data of the reviewer or staff.
- Keep it short: 2-4 sentences, plain text only (no markdown, no emoji spam).
- NEVER use em dashes (—). This is strict: no em dash anywhere in the reply. Use commas or periods instead.
- Only state business facts (products, menus, prices, hours, services) that appear in
  the business-facts context below. If there is no such context, or it does not cover
  what the reviewer asks: NEVER invent products, menus, prices, availability or hours.
  Say the team will follow up with accurate details and invite them to visit or contact.

Tone: {tone}.
{rating_guidance}
{custom_block}
{context_block}
{retry_block}
{language_block}
{marketing_block}
Write only the reply text — nothing else."""

POSITIVE_GUIDANCE = "This is a positive review: thank the reviewer warmly and mention something specific they praised if possible."
NEUTRAL_GUIDANCE = "This is a neutral review: thank the reviewer and invite constructive feedback."
NEGATIVE_GUIDANCE = "This is a negative review: acknowledge the specific complaint, apologise sincerely, and offer to make it right. Do not be defensive. Do not dispute their account."
QUESTION_GUIDANCE = (
    "This review is a QUESTION from a potential customer, not feedback: do NOT thank them "
    "for their review or rating, and do not praise their feedback. Answer the question "
    "directly and briefly, using only verified business facts."
)


def _rating_guidance(rating: int) -> str:
    if rating >= 4:
        return POSITIVE_GUIDANCE
    if rating == 3:
        return NEUTRAL_GUIDANCE
    return NEGATIVE_GUIDANCE


async def _channel_owner_id(channel_id: str | None, db: AsyncSession) -> str | None:
    """Tenant id for metering (never raises)."""
    if not channel_id:
        return None
    try:
        from sqlalchemy import select

        from .models import Channel

        return (await db.execute(
            select(Channel.user_id).where(Channel.id == channel_id)
        )).scalar_one_or_none()
    except Exception:
        return None


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
    attempt: int = 1,
    previous_draft: str | None = None,
) -> str:
    """Generate a public reply to a review using the channel's configured model/tone.

    `attempt` > 1 marks a regenerate/retry: `previous_draft` (the wording the
    merchant rejected) is shown to the model so the new draft differs.
    """
    retry_block = ""
    if attempt > 1 and (previous_draft or "").strip():
        retry_block = (
            f"This is attempt #{attempt} of drafting a reply for this review.\n"
            f"Previous draft the merchant rejected:\n\"{previous_draft.strip()[:800]}\"\n"
            "Write a DIFFERENT reply — keep the same policy and tone, but do not "
            "reuse the previous draft's wording, opening line or structure."
        )
    elif attempt > 1:
        retry_block = (
            f"This is attempt #{attempt} of drafting a reply for this review "
            "(earlier attempts failed to generate)."
        )
    # Question-type reviews: an inquiry is not feedback. Thanking
    # "هل تبيعون شاورما؟" for a "wonderful review" is nonsense.
    from ..review_engine.understanding import looks_like_question

    is_question = looks_like_question(review_text)
    lang = _review_language(review_text)
    policy = (getattr(config, "reply_language", None) or "match").strip().lower()
    if policy not in ("match", "en", "ar"):
        policy = "match"
    eff = policy if policy in ("en", "ar") else (lang or "en")
    dialect_entry = None
    dialect_code = (getattr(config, "dialect", None) or "auto").strip().lower()
    if eff == "ar" and dialect_code not in ("", "auto"):
        try:
            from ..review_engine.dialects import get_dialect as _get_dialect

            dialect_entry = await _get_dialect(dialect_code, db)
        except Exception:
            dialect_entry = None
    if eff == "ar":
        language_block = (
            "Language: write your ENTIRE reply in Arabic (العربية). Never switch to English."
        )
        if dialect_entry:
            examples = " / ".join(dialect_entry.get("examples", [])[:4])
            language_block += (
                f" Dialect (binding): write in {dialect_entry.get('dialect_en')} "
                f"({dialect_entry.get('dialect_ar')}). Copy this flavor: {examples}. "
                f"Do not mix dialects."
            )
    elif lang == "ar":
        language_block = (
            "Language: write your ENTIRE reply in English, even though the review "
            "is in Arabic — never switch languages."
        )
    else:
        language_block = (
            "Language: reply in the SAME language as the review — an Arabic review "
            "gets an Arabic reply, an English review gets an English reply."
        )
    marketing_block = ""
    if getattr(config, "promo_product_mentions", False) or getattr(config, "promo_links", False):
        max_ctas = getattr(config, "promo_max_ctas", 1) or 1
        bits = []
        if getattr(config, "promo_product_mentions", False):
            bits.append("you may name a relevant product/service by its exact name")
        if getattr(config, "promo_links", False):
            bits.append(
                f"you may include at most {max_ctas} link(s), ONLY a URL that appears "
                f"verbatim in the business facts below — never invent one"
            )
        if getattr(config, "promo_only_relevant", True):
            bits.append("only when directly relevant to what the reviewer wrote")
        marketing_block = (
            "Merchant allows promotion in replies: " + "; ".join(bits) + "."
        )

    # Dev mock mode: canned, policy-safe replies — no LLM call.
    from ...config import settings as _settings
    if _settings.GOOGLE_REVIEWS_MOCK:
        name = reviewer_name.split(" ")[0] if reviewer_name else "there"
        if looks_like_question(review_text):
            if lang == "ar":
                return (
                    f"شكراً على سؤالك يا {name}! يسعدنا مساعدتك، وتواصل معنا مباشرة "
                    f"حتى نعطيك التفاصيل الدقيقة ونعود إليك بالرد."
                )
            return (
                f"Thanks for the question, {name}! Happy to help — reach out to us "
                f"directly and we'll follow up with the exact details."
            )
        if lang == "ar":
            if rating >= 4:
                return (
                    f"شكراً جزيلاً يا {name}! سعدنا بتجربتك الرائعة معنا، وآراء مثل رأيك "
                    f"تحفز فريقنا على الاستمرار. نتطلع لرؤيتك مرة أخرى قريباً!"
                )
            if rating == 3:
                return (
                    f"شكراً لملاحظاتك الصادقة يا {name}. يسعدنا أن جزءاً من تجربتك كان جيداً، "
                    f"ونحب أن نسمع رأيك فيما يمكننا تحسينه في المرة القادمة."
                )
            return (
                f"نعتذر بشدة عن تجربتك يا {name}. هذا ليس المستوى الذي نسعى إليه. "
                f"يرجى التواصل معنا مباشرة حتى نصلح الأمر."
            )
        if rating >= 4:
            return (
                f"Thank you so much, {name}! We're happy you had a great experience "
                f"with us, feedback like yours keeps our team motivated. We hope to see you again soon!"
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
        rating_guidance=QUESTION_GUIDANCE if is_question else _rating_guidance(rating),
        custom_block=custom_block,
        context_block=context_block,
        retry_block=retry_block,
        language_block=language_block,
        marketing_block=marketing_block,
    )

    review_desc = review_text.strip() if review_text and review_text.strip() else "(no written comment, star rating only)"
    user_msg = f"Review by {reviewer_name or 'an anonymous customer'} — {rating}/5 stars:\n\"{review_desc}\""

    provider = get_provider_for_model(config.model)
    from ..llm.service import _resolve_model
    api_model, _ = _resolve_model(config.model)

    tenant_id = await _channel_owner_id(getattr(config, "channel_id", None), db)

    # Close DB before LLM call to free connection
    await db.close()

    req = LLMRequest(
        model=api_model,
        messages=[LLMMessage(role="user", content=user_msg)],
        system_prompt=system_prompt,
        temperature=0.6,
        max_tokens=300,
        stream=False,
        tenant_id=tenant_id,
        model_id=config.model,
        purpose="auto_reply.review",
        channel_id=getattr(config, "channel_id", None),
    )
    try:
        resp = await provider.complete(req)
    except ProviderError:
        # No fallback: the configured model is the tenant's choice from the
        # database. A dead model must fail loudly so the admin fixes the
        # key, not silently switch bills to another provider.
        raise
    reply = resp.content.strip()
    if not reply:
        raise ProviderError(config.model, "Empty reply generated", 502)
    # Guarantee: no em dash may reach the merchant, even if the model
    # ignored the ban.
    from ..review_engine.validator import strip_em_dashes

    cleaned = strip_em_dashes(reply)
    if cleaned != reply:
        logger.warning("Stripped em dash(es) from simple-prompt reply")
    return cleaned


async def generate_auto_reply(
    config: AutoReplyConfig,
    channel,
    rating: int,
    review_text: str | None,
    reviewer_name: str | None,
    db: AsyncSession,
    review_id: str | None = None,
    attempt: int = 1,
    previous_draft: str | None = None,
) -> str:
    """Draft entry point for the auto-pipelines (worker + Localith sync).

    Prefers the agentic review engine (analysis → strategies → tools →
    validation → brand voice) for every generation — retries included,
    with the rejected draft passed along so the engine writes a clearly
    different reply. Falls back to the simple single-shot prompt when the
    engine is unavailable or the review has no text (star-only).
    """
    from ...config import settings as _settings

    if _settings.GOOGLE_REVIEWS_MOCK:
        return await generate_review_reply(config, rating, review_text, reviewer_name, db)

    if (review_text or "").strip():
        try:
            from ..review_engine.schemas import ReviewEngineRequest
            from ..review_engine.service import process_review

            req = ReviewEngineRequest(
                review_text=review_text.strip()[:5000],
                rating=rating,
                reviewer_name=(reviewer_name or None),
                review_id=(review_id[:120] if review_id else None),
                channel="google_review",
                channel_id=getattr(channel, "id", None),
                previous_draft=(previous_draft or None),
            )
            resp = await process_review(req, getattr(channel, "user_id", None), db)
            text = (resp.response_text or "").strip()
            if text:
                return text
            logger.warning("Review engine returned empty text; using simple prompt fallback")
        except Exception as e:
            logger.warning("Review engine failed (%s); using simple prompt fallback", e)

    return await generate_review_reply(
        config, rating, review_text, reviewer_name, db,
        attempt=attempt, previous_draft=previous_draft,
    )

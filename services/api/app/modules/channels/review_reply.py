"""Merchant replies to Google reviews — single production path: the engine.

All generations (auto-pipelines, manual drafts, regenerations, retries)
flow through the review engine (analysis → strategies → Retrieval Layer
evidence → generation → validation). There is no legacy single-shot
fallback: engine errors propagate so failures land in the approval queue
as "failed" with Retry, never as silent generic text.

Dev mock mode (GOOGLE_REVIEWS_MOCK) returns canned policy-safe replies.
"""
import logging
import re

from sqlalchemy.ext.asyncio import AsyncSession

from ..llm.providers.base import ProviderError
from .models import AutoReplyConfig

logger = logging.getLogger(__name__)

# Arabic-script characters (also covers Urdu, Persian) — mock replies match
# the review language (Arabic review → Arabic reply).
_ARABIC_SCRIPT = re.compile(r"[؀-ۿ]")


def _mock_reply(rating: int, review_text: str | None,
                reviewer_name: str | None) -> str:
    """Canned, policy-safe replies for dev mock mode — no LLM call."""
    from ..review_engine.understanding import looks_like_question

    lang = "ar" if review_text and _ARABIC_SCRIPT.search(review_text) else None
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
    """Draft a reply via the review engine. Star-only reviews included —
    the engine runs with no product reference and needs no evidence.

    Engine errors propagate (no silent fallback): callers record a "failed"
    row and notify, and the merchant retries from the queue.
    """
    from ...config import settings as _settings

    if _settings.GOOGLE_REVIEWS_MOCK:
        return _mock_reply(rating, review_text, reviewer_name)

    from ..review_engine.schemas import ReviewEngineRequest
    from ..review_engine.service import process_review

    req = ReviewEngineRequest(
        review_text=(review_text or "").strip()[:5000],
        rating=rating,
        reviewer_name=(reviewer_name or None),
        review_id=(review_id[:120] if review_id else None),
        channel="google_review",
        channel_id=getattr(channel, "id", None),
        previous_draft=(previous_draft or None),
    )
    resp = await process_review(req, getattr(channel, "user_id", None), db)
    text = (resp.response_text or "").strip()
    if not text:
        raise ProviderError(
            getattr(config, "model", "engine"), "Empty reply generated", 502
        )
    # Guarantee: no em dash may reach the merchant, even if the model
    # ignored the ban.
    from ..review_engine.validator import strip_em_dashes

    cleaned = strip_em_dashes(text)
    if cleaned != text:
        logger.warning("Stripped em dash(es) from engine reply")
    return cleaned

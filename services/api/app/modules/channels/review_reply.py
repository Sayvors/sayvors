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

# The one line added to needs-attention replies: an invitation to continue
# privately, with the wa.me deep link that prefills the handoff code. Both
# stay inside the validator's bans by construction — no em dash (strip_em_dashes
# would mangle it), no promo vocabulary ("code", "offer", "discount" never
# appear).
_HANDOFF_LINE_EN = "To sort this out quickly, message us on WhatsApp:"
_HANDOFF_LINE_AR = "لحل الأمر سريعاً، راسلنا على واتساب:"
_SALES_LINE_EN = "We can share the details privately on WhatsApp:"
_SALES_LINE_AR = "يمكننا مشاركة التفاصيل على واتساب:"

# Google caps the public review reply at 4000 characters. Engine replies
# target <=90 words, so this is belt-and-braces — but the guard is one
# comparison and the API error otherwise costs a "failed" row.
_REPLY_MAX_CHARS = 4000


async def _append_handoff_link(
    text: str,
    db: AsyncSession,
    channel,
    review_id: str | None,
    review_text: str | None,
    config=None,
) -> str:
    """Offer a private WhatsApp continuation on needs-attention reviews.

    The link prefills the handoff code, so the customer taps, hits send, and
    the WhatsApp assistant already holds the ticket (consumer.py resolves it
    and injects the classification into the reply prompt).

    Read-only by design: it USES a code the classification pipeline minted and
    never commits. A commit here would expire the caller's ORM objects
    mid-flow — the exact MissingGreenlet hazard scheduling.take_lock documents
    (the poll loop touches `failed_row` immediately after this returns). An
    issue without a code (praise, or classification not finished yet) simply
    gets no link; the next regeneration picks it up.

    Any failure degrades to the un-appended reply: a missing link must never
    cost the merchant their reply.
    """
    if not text or not review_id or "wa.me/" in text:
        return text
    # Tenant opt-out (auto_reply_configs.handoff_link_enabled, default ON):
    # the link publishes the WhatsApp number on a public listing, so the
    # tenant gets the final say. getattr-default keeps direct callers and
    # pre-migration objects on the enabled default.
    if config is not None and not getattr(config, "handoff_link_enabled", True):
        return text
    try:
        from sqlalchemy import select

        from ..review_engine.handoff import tenant_whatsapp_number, wa_me_link
        from .models import ReviewIssue

        code = (await db.execute(
            select(ReviewIssue.handoff_code)
            .where(
                ReviewIssue.channel_id == getattr(channel, "id", None),
                ReviewIssue.review_id == review_id,
                ReviewIssue.needs_attention.is_(True),
                ReviewIssue.handoff_code.isnot(None),
            )
            .order_by(ReviewIssue.created_at.desc())
            .limit(1)
        )).scalar_one_or_none()
        if not code:
            return text
        number = await tenant_whatsapp_number(
            db, tenant_id=getattr(channel, "user_id", None)
        )
        link = wa_me_link(number or "", code)
        if not link:
            return text
        line = (
            _HANDOFF_LINE_AR
            if review_text and _ARABIC_SCRIPT.search(review_text)
            else _HANDOFF_LINE_EN
        )
        addition = f"{line} {link}"
        if len(text) + len(addition) + 1 > _REPLY_MAX_CHARS:
            return text
        return f"{text}\n{addition}"
    except Exception as e:
        logger.warning("handoff link append failed for %s: %s", review_id, e)
        return text


async def _append_sales_link(
    text: str,
    db: AsyncSession,
    channel,
    review_id: str | None,
    review_text: str | None,
    config=None,
) -> str:
    """Offer a generic WhatsApp conversation for purchase/pricing questions.

    This is deliberately NOT a ticket handoff. The reviewer gets the business's
    normal WhatsApp number with no code, so the conversation is captured as a
    lead and the assistant can answer from the databank. Complaint handoffs keep
    their own code-bearing link and are handled by _append_handoff_link first.
    """
    if not text or not review_id or "wa.me/" in text:
        return text
    if config is not None and not getattr(config, "handoff_link_enabled", True):
        return text

    try:
        from sqlalchemy import select

        from ..review_engine.handoff import tenant_whatsapp_number
        from .models import ReviewIssue

        issue = (
            await db.execute(
                select(ReviewIssue)
                .where(
                    ReviewIssue.channel_id == getattr(channel, "id", None),
                    ReviewIssue.review_id == review_id,
                )
                .order_by(ReviewIssue.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if issue is not None and issue.needs_attention:
            return text  # complaint path: its code-bearing link is authoritative

        commercial = bool(
            issue is not None
            and issue.primary_category in {"information_inquiries", "pricing_promotions"}
            and issue.intent in {"ask_question", "information_request"}
        )
        if issue is None:
            from ..review_engine.understanding import looks_like_question

            commercial = looks_like_question(review_text)
        if not commercial:
            return text

        number = await tenant_whatsapp_number(
            db, tenant_id=getattr(channel, "user_id", None)
        )
        if not number:
            return text
        link = f"https://wa.me/{number}"
        line = (
            _SALES_LINE_AR
            if review_text and _ARABIC_SCRIPT.search(review_text)
            else _SALES_LINE_EN
        )
        addition = f"{line} {link}"
        if len(text) + len(addition) + 1 > _REPLY_MAX_CHARS:
            return text
        return f"{text}\n{addition}"
    except Exception as e:
        logger.warning("sales link append failed for %s: %s", review_id, e)
        return text


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
        if review_text and re.search(
            r"(?:مبن|عمار|مرفق).{0,30}(?:تصلح|صلح|ترميم|صيان|إصلاح|اصلاح)|(?:تصلح|صلح|ترميم|صيان|إصلاح|اصلاح).{0,30}(?:مبن|عمار|مرفق)",
            review_text,
        ):
            return (
                "نعتذر عن حالة المبنى، وشكرًا لتنبيهنا. نرجو مراسلتنا على الخاص "
                "بتفاصيل أكثر لنتمكن من متابعة الأمر."
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
        # Mock mode changes the wording, not the product contract: a
        # needs-attention reviewer still gets the WhatsApp handoff link.
        mock_text = await _append_handoff_link(
            _mock_reply(rating, review_text, reviewer_name),
            db, channel, review_id, review_text, config=config,
        )
        return await _append_sales_link(
            mock_text, db, channel, review_id, review_text, config=config
        )

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
    with_handoff = await _append_handoff_link(
        cleaned, db, channel, review_id, review_text, config=config
    )
    return await _append_sales_link(
        with_handoff, db, channel, review_id, review_text, config=config
    )

"""Search and match response strategies against a review analysis."""
import json
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .issues import detect_churn
from .models import ResponseStrategy
from .schemas import ReviewAnalysis, StrategyMatch, SuppressedStrategy

logger = logging.getLogger(__name__)


async def search_strategies(
    analysis: ReviewAnalysis,
    channel: str,
    db: AsyncSession,
) -> list[StrategyMatch]:
    """Return strategies relevant to the given review analysis, ordered by priority."""
    result = await db.execute(
        select(ResponseStrategy).where(ResponseStrategy.enabled == True)
    )
    all_strategies = result.scalars().all()

    matches: list[StrategyMatch] = []

    for s in all_strategies:
        if not _matches_channel(s, channel):
            continue
        if not _matches_conditions(s, analysis):
            continue

        reason = _explain_match(s, analysis)
        matches.append(StrategyMatch(
            strategy_id=s.id,
            name=s.name,
            reason=reason,
            priority=s.priority,
        ))

    matches.sort(key=lambda m: m.priority, reverse=True)
    return matches


# ── Conflict resolution (eligibility gating) ─────────────

# Priority tiers: required strategies must be fulfilled (fail blocks approval);
# best-effort strategies are warnings only — never pad the reply for them.
STRATEGY_PRIORITY: dict[str, str] = {
    "address_specific_issue": "critical",
    "apologize_for_issue": "critical",
    "invite_private_conversation": "critical",
    "acknowledge_feedback": "high",
    "show_appreciation": "high",
    "reassure_customer": "high",
    "keep_response_minimal": "high",
    "encourage_another_visit": "medium",
    "mention_relevant_offer": "low",
    "recommend_related_product": "low",
}

BEST_EFFORT: frozenset[str] = frozenset({
    "encourage_another_visit",
    "mention_relevant_offer",
    "recommend_related_product",
})

# Growth strategies that must not fire at a churning customer.
CHURN_SUPPRESSED = {"mention_relevant_offer", "recommend_related_product"}

# Recovery strategies that are only credible after a real recovery statement.
CHURN_CONDITIONAL = {"encourage_another_visit"}

import re as _re

# Customer explicitly wants alternatives/a deal → sales strategies eligible.
ALTERNATIVE_REQUEST = _re.compile(
    r"\b(recommend|suggest|alternative|other options?|cheaper options?|less expensive|lower (priced|tier|plan)|options do you have|instead|different (product|plan|option)|switch to|what else)\b",
    _re.I,
)
OFFER_REQUEST = _re.compile(
    r"\b(discount|coupon|voucher|credit|compensation|promo(code)?|deal|make (it|this) up)\b",
    _re.I,
)
# Customer signals they will re-engage on their own.
RETURN_INTENT = _re.compile(
    r"\b(will (come|be) back|give (you|it|them) another (try|chance|shot|opportunity)|try again|next time|see you (soon|again))\b",
    _re.I,
)
BILLING_KEYS = {"billing"}
BILLING_SIGNAL = _re.compile(
    r"\b(charged twice|double charg\w*|wrong (amount|bill)|unexpected charg\w*|payment (failed|declined|error)|invoices? (is|was|are) (wrong|incorrect)|billing error|money back|refund\b)\b",
    _re.I,
)
PRICING_KEYS = {"pricing"}
PRICING_SIGNAL = _re.compile(
    r"\b(too expensive|overpriced|pricey|costly|price (is |feels )?too high|not worth (the|its|their) (price|money|cost)|costs too much)\b",
    _re.I,
)


def _context_flags(analysis: ReviewAnalysis, review_text: str) -> dict:
    """Shared complaint-context signals for eligibility and selection."""
    text = review_text or ""
    billing_ctx = (
        (analysis.issue_type or "") in BILLING_KEYS
        or "refund_request" in (analysis.intent or [])
        or bool(BILLING_SIGNAL.search(text))
    )
    return {
        "text": text,
        "churn": detect_churn(text),
        "negative": analysis.sentiment in ("negative", "very_negative"),
        "very_negative": analysis.sentiment == "very_negative",
        "billing_ctx": billing_ctx,
        "pricing_ctx": (
            (analysis.issue_type or "") in PRICING_KEYS
            or bool(PRICING_SIGNAL.search(text))
        ),
        "wants_alternative": bool(ALTERNATIVE_REQUEST.search(text)),
        "wants_offer": bool(OFFER_REQUEST.search(text)),
        "return_intent": bool(RETURN_INTENT.search(text)),
        "high_urgency": (analysis.urgency or "low") in ("high", "critical"),
        "medium_urgency": (analysis.urgency or "low") in ("medium", "high", "critical"),
    }


def resolve_strategy_conflicts(
    matches: list[StrategyMatch],
    analysis: ReviewAnalysis,
    review_text: str,
) -> tuple[list[StrategyMatch], list[SuppressedStrategy]]:
    """Split semantic matches into eligible vs suppressed.

    Matching answers "is this relevant?"; resolution answers "may it run?".
    Suppression reasons are returned for the trace — nothing is dropped silently.
    """
    ctx = _context_flags(analysis, review_text)
    text = ctx["text"]
    churn = ctx["churn"]
    negative = ctx["negative"]
    billing_ctx = ctx["billing_ctx"]
    pricing_ctx = ctx["pricing_ctx"]
    wants_alternative = ctx["wants_alternative"]
    wants_offer = ctx["wants_offer"]
    return_intent = ctx["return_intent"]

    active: list[StrategyMatch] = []
    suppressed: list[SuppressedStrategy] = []

    def _money_prefix() -> str:
        if billing_ctx:
            return "Billing/refund complaint — "
        if pricing_ctx:
            return "Pricing concern — "
        return ""

    for m in matches:
        sid = m.strategy_id
        # Hard eligibility: product recommendations need an explicit request.
        # Mentioning a product is NOT asking for another one.
        if sid == "recommend_related_product" and not wants_alternative:
            if churn:
                reason = "Customer signaled churn — no product pitch."
            else:
                reason = (f"{_money_prefix()}no explicit request for alternatives, "
                          f"recommendations, or a replacement — complaint context only.")
            suppressed.append(SuppressedStrategy(strategy_id=sid, name=m.name, reason=reason))
            continue
        # Hard eligibility for offers:
        # - explicit compensation/deal request → eligible;
        # - churn or billing trouble without a request → suppressed;
        # - genuine pricing objection → eligible CONDITIONALLY: a VERIFIED
        #   relevant offer must be retrieved (verified at prune). No literal
        #   "discount" ask needed — the objection itself justifies the lookup.
        # - anything else → suppressed.
        if sid == "mention_relevant_offer" and not wants_offer:
            product_ref = (analysis.product_reference or "").strip()
            if churn:
                reason = "Customer signaled churn ('never coming back' pattern) — promotional content suppressed."
            elif billing_ctx:
                reason = ("Billing trouble — offers suppressed unless the customer asks "
                          "for compensation or a deal.")
            elif pricing_ctx:
                scope = f" matching '{product_ref}'" if product_ref else ""
                m = m.model_copy(update={
                    "conditional": True,
                    "condition_note": (
                        f"Pricing objection raised — a VERIFIED relevant offer{scope} retrieved from the "
                        f"databank MAY be mentioned briefly with exact terms. "
                        f"No verified relevant offer means no mention."
                    ),
                })
                active.append(m)
                continue
            else:
                reason = ("No explicit request for compensation, a discount, or a deal — "
                          "nothing to offer unprompted.")
            suppressed.append(SuppressedStrategy(strategy_id=sid, name=m.name, reason=reason))
            continue
        # Re-engagement invitations: complaints get recovery + next step, not a
        # visit pitch — unless the customer signals they will return.
        if sid == "encourage_another_visit" and negative and not return_intent:
            suppressed.append(SuppressedStrategy(
                strategy_id=sid, name=m.name,
                reason="Complaint context — recovery and a useful next step take priority over a re-engagement pitch.",
            ))
            continue
        if sid in CHURN_CONDITIONAL and negative and return_intent:
            m = m.model_copy(update={
                "conditional": True,
                "condition_note": "Only invite back after a credible apology and specific recovery statement — no pressure.",
                "priority": max(0, m.priority - 30),
            })
        # Minimal responses must not upsell.
        if m.strategy_id in CHURN_SUPPRESSED and any(
            a.strategy_id == "keep_response_minimal" for a in active
        ):
            suppressed.append(SuppressedStrategy(
                strategy_id=m.strategy_id, name=m.name,
                reason="Suppressed by keep_response_minimal — short review, no promotions.",
            ))
            continue
        active.append(m)

    active.sort(key=lambda m: m.priority, reverse=True)
    return active, suppressed


def select_execution_set(
    eligible: list[StrategyMatch],
    suppressed: list[SuppressedStrategy],
    analysis: ReviewAnalysis,
    issues: list,
    review_text: str,
) -> tuple[list[StrategyMatch], list[SuppressedStrategy]]:
    """Pick the MINIMAL strategy set that answers this review.

    Eligibility is not execution: a strategy can be allowed yet unused when
    it adds no     customer value within the word budget. Deferred strategies
    are recorded with reasons — like suppression, but "not needed" rather
    than "forbidden". Returns (execute, suppressed+deferred).
    """
    ctx = _context_flags(analysis, review_text)
    concrete = [i for i in (issues or []) if not getattr(i, "generic", False)]
    suppressed = list(suppressed)
    execute: list[StrategyMatch] = []

    def _defer(m: StrategyMatch, reason: str) -> None:
        suppressed.append(SuppressedStrategy(
            strategy_id=m.strategy_id, name=m.name,
            reason=f"Deferred (eligible but unused): {reason}",
        ))

    for m in eligible:
        sid = m.strategy_id
        # Nothing concrete to address → addressing is noise.
        if sid == "address_specific_issue" and not issues:
            _defer(m, "no extracted facts to address — acknowledgment covers it.")
            continue
        # Apology earns its place on severity, not by default.
        if sid == "apologize_for_issue":
            if ctx["very_negative"] or (
                ctx["negative"] and (
                    bool(concrete) or ctx["churn"]
                    or ctx["billing_ctx"] or "refund_request" in (analysis.intent or [])
                    or ctx["medium_urgency"]
                )
            ):
                execute.append(m)
            else:
                _defer(m, "low-severity complaint — acknowledgment suffices, no apology needed.")
            continue
        # Reassurance earns its place on gravity.
        if sid == "reassure_customer":
            if ctx["very_negative"] or ctx["churn"] or ctx["billing_ctx"] \
                    or "refund_request" in (analysis.intent or []) or ctx["high_urgency"]:
                execute.append(m)
            else:
                _defer(m, "moderate complaint — recovery statement suffices, no separate reassurance needed.")
            continue
        execute.append(m)

    if not execute and eligible:
        # Never return empty: keep the highest-priority eligible strategy.
        top = max(eligible, key=lambda s: s.priority)
        execute.append(top)
        suppressed[:] = [s for s in suppressed
                         if not (s.strategy_id == top.strategy_id and s.reason.startswith("Deferred"))]

    execute.sort(key=lambda m: m.priority, reverse=True)
    return execute, suppressed


def offer_matches_product(product_ref: str | None, offer_texts: list[str]) -> bool:
    """Does any retrieved offer verifiably cover the mentioned product?

    Whole-word match on significant product words, or a genuinely general
    offer (sitewide / all plans). Prevents attaching unrelated promotions
    to a complaint just because an offer exists.
    """
    if not product_ref or not offer_texts:
        return False
    stop = {"the", "and", "for", "with", "your", "our", "this", "that", "new", "app", "pro"}
    words = [w for w in _re.findall(r"[a-z0-9]{2,}", product_ref.lower()) if w not in stop]
    general = ("all products", "all plans", "sitewide", "storewide",
               "everything", "any plan", "all services", "store wide")
    for t in offer_texts:
        tl = (t or "").lower()
        if any(_re.search(rf"\b{_re.escape(w)}\b", tl) for w in words):
            return True
        if any(g in tl for g in general):
            return True
    return False


# Pricing-relevant offer signals for product-less pricing objections.
PRICING_OFFER_WORDS = ("discount", "coupon", "%", "percent", "pricing", "price",
                       "promo", "sale", "voucher")


def offer_justified_for_pricing(
    product_ref: str | None, offer_texts: list[str]
) -> bool:
    """A pricing-objection offer is justified iff a retrieved offer is relevant:
    product-matched when a product was mentioned, pricing-relevant otherwise."""
    if not offer_texts:
        return False
    if product_ref:
        return offer_matches_product(product_ref, offer_texts)
    return any(w in (t or "").lower() for t in offer_texts for w in PRICING_OFFER_WORDS)


def prune_unsatisfiable(
    strategies: list[StrategyMatch],
    suppressed: list[SuppressedStrategy],
    *,
    has_offer_data: bool,
    has_product_data: bool,
    product_ref: str | None = None,
    offer_texts: list[str] | None = None,
) -> tuple[list[StrategyMatch], list[SuppressedStrategy]]:
    """Remove strategies whose hard dependencies came back empty — BEFORE generation.

    A strategy that cannot possibly be satisfied must never burn LLM attempts
    in validation. Returns (active, suppressed) with new suppressions appended.
    """
    active: list[StrategyMatch] = []
    suppressed = list(suppressed)
    for m in strategies:
        if m.strategy_id == "mention_relevant_offer":
            if not has_offer_data:
                suppressed.append(SuppressedStrategy(
                    strategy_id=m.strategy_id, name=m.name,
                    reason="Offer lookup returned no verified offer — removed before generation instead of failing validation.",
                ))
                continue
            if m.conditional and not offer_justified_for_pricing(product_ref, offer_texts or []):
                suppressed.append(SuppressedStrategy(
                    strategy_id=m.strategy_id, name=m.name,
                    reason="No retrieved offer is relevant to this pricing objection — "
                           "removed before generation instead of inventing one.",
                ))
                continue
            if not m.conditional and product_ref and not offer_matches_product(product_ref, offer_texts or []):
                # Explicit request, but the only data is for other products.
                suppressed.append(SuppressedStrategy(
                    strategy_id=m.strategy_id, name=m.name,
                    reason=f"No retrieved offer matches '{product_ref}' — removed before generation instead of inventing one.",
                ))
                continue
        if m.strategy_id == "recommend_related_product" and not has_product_data:
            suppressed.append(SuppressedStrategy(
                strategy_id=m.strategy_id, name=m.name,
                reason="No verified product data retrieved — removed before generation instead of failing validation.",
            ))
            continue
        active.append(m)
    return active, suppressed


def _matches_channel(strategy: ResponseStrategy, channel: str) -> bool:
    if not strategy.channel_restrictions:
        return True
    return channel in strategy.channel_restrictions


def _matches_conditions(strategy: ResponseStrategy, analysis: ReviewAnalysis) -> bool:
    conds = strategy.conditions or {}
    if not conds:
        return True

    allowed_sentiments = conds.get("sentiments")
    if allowed_sentiments and analysis.sentiment not in allowed_sentiments:
        return False

    allowed_issue_types = conds.get("issue_types")
    if allowed_issue_types and analysis.issue_type:
        if analysis.issue_type not in allowed_issue_types:
            return False

    if conds.get("has_text") and not analysis.product_reference and not analysis.issue_type:
        review_text_len = len(analysis.customer_request or "")
        if review_text_len < 5:
            return False

    if conds.get("has_product_reference") and not analysis.product_reference:
        return False

    max_len = conds.get("max_review_length")
    if max_len:
        text_len = len(analysis.customer_request or "")
        if text_len > max_len:
            return False

    intent_kws = conds.get("intent_keywords")
    if intent_kws:
        text_lower = " ".join(analysis.intent).lower()
        if not any(kw in text_lower for kw in intent_kws):
            text_lower_combined = (
                (analysis.customer_request or "").lower()
                + " " + (analysis.product_reference or "").lower()
            )
            if not any(kw in text_lower_combined for kw in intent_kws):
                return False

    return True


def _explain_match(strategy: ResponseStrategy, analysis: ReviewAnalysis) -> str:
    conds = strategy.conditions or {}
    parts = []

    allowed_sentiments = conds.get("sentiments")
    if allowed_sentiments:
        parts.append(f"review is {analysis.sentiment}")

    allowed_issues = conds.get("issue_types")
    if allowed_issues and analysis.issue_type:
        parts.append(f"issue is {analysis.issue_type}")

    if conds.get("has_product_reference") and analysis.product_reference:
        parts.append(f"mentions {analysis.product_reference}")

    intent_kws = conds.get("intent_keywords")
    if intent_kws:
        parts.append(f"intent matches keywords")

    if not parts:
        parts.append("general match")

    return "; ".join(parts)


# ── Constants ────────────────────────────────────────────

CORE_STRATEGIES = [
    {
        "id": "acknowledge_feedback",
        "name": "Acknowledge Feedback",
        "description": "Recognize what the customer actually said. Reference the specific subject of the review.",
        "category": "engagement",
        "conditions": {"sentiments": ["neutral", "positive", "negative", "very_negative", "very_positive"], "min_length": 10},
        "instructions": ["Reference the specific subject of the review, not a generic 'your feedback'.", "Show that the review was read and understood."],
        "compatible_strategies": ["show_appreciation", "apologize_for_issue", "address_specific_issue", "keep_response_minimal"],
        "priority": 90,
    },
    {
        "id": "apologize_for_issue",
        "name": "Apologize for Issue",
        "description": "Acknowledge the problem and apologize naturally when the customer reports a negative experience.",
        "category": "recovery",
        "conditions": {"sentiments": ["negative", "very_negative"], "issue_types": ["product_quality", "product_dissatisfaction", "service_quality", "delivery", "wait_time", "cleanliness", "staff_behavior", "billing", "pricing", "technical_issue", "general_complaint"]},
        "instructions": ["Acknowledge the specific problem mentioned.", "Apologize naturally without excessive repetition.", "Do not argue with the customer.", "Avoid generic apologies that don't address the issue.", "Do not make unsupported promises about fixes."],
        "compatible_strategies": ["acknowledge_feedback", "address_specific_issue", "reassure_customer", "invite_private_conversation"],
        "priority": 80,
    },
    {
        "id": "show_appreciation",
        "name": "Show Appreciation",
        "description": "Thank the reviewer for positive reviews, constructive feedback, or detailed reviews.",
        "category": "engagement",
        "conditions": {"sentiments": ["positive", "very_positive"]},
        "instructions": ["Thank the reviewer warmly but proportionally.", "If the review is detailed, acknowledge something specific.", "Do not be overly effusive for a simple 'great'."],
        "compatible_strategies": ["acknowledge_feedback", "encourage_another_visit", "keep_response_minimal"],
        "priority": 85,
    },
    {
        "id": "address_specific_issue",
        "name": "Address Specific Issue",
        "description": "Directly address the primary issue mentioned in the review rather than giving a generic response.",
        "category": "engagement",
        "conditions": {"sentiments": ["negative", "very_negative", "neutral"], "has_text": True},
        "instructions": ["Identify the primary issue from the review.", "Discuss the specific issue in the response.", "Do not deflect or redirect to unrelated topics."],
        "compatible_strategies": ["acknowledge_feedback", "apologize_for_issue", "reassure_customer"],
        "priority": 75,
    },
    {
        "id": "reassure_customer",
        "name": "Reassure Customer",
        "description": "Provide reasonable reassurance without making unsupported claims about fixes or changes.",
        "category": "recovery",
        "conditions": {"sentiments": ["negative", "very_negative"], "issue_types": ["product_quality", "service_quality", "staff_behavior", "cleanliness", "technical_issue", "pricing"]},
        "instructions": ["Express that the feedback is taken seriously.", "Do not claim the issue has been fixed unless there is evidence.", "Keep reassurance proportional to the complaint."],
        "compatible_strategies": ["acknowledge_feedback", "apologize_for_issue", "invite_private_conversation"],
        "priority": 60,
    },
    {
        "id": "recommend_related_product",
        "name": "Recommend Related Product",
        "description": "Recommend another product or service when genuinely relevant to the customer's complaint.",
        "category": "growth",
        "conditions": {"sentiments": ["negative", "very_negative", "neutral"], "has_product_reference": True},
        "instructions": ["Only recommend products that actually exist in the business catalog.", "Frame the recommendation as a genuine alternative, not a sales pitch.", "Connect the recommendation to what the customer didn't like."],
        "compatible_strategies": ["acknowledge_feedback", "mention_relevant_offer", "encourage_another_visit"],
        "priority": 40,
    },
    {
        "id": "mention_relevant_offer",
        "name": "Mention Relevant Offer",
        "description": "Retrieve and mention an existing active promotion when appropriate. Must never invent offers.",
        "category": "growth",
        "conditions": {"sentiments": ["negative", "very_negative", "neutral"]},
        "instructions": ["Retrieve relevant active offers from the business before responding.", "Only mention offers that actually exist and are publicly mentionable.", "Integrate the offer naturally into the response.", "If no relevant offer exists, do NOT mention any offer.", "Never invent a discount, coupon, or promotion."],
        "compatible_strategies": ["acknowledge_feedback", "apologize_for_issue", "encourage_another_visit", "recommend_related_product"],
        "priority": 35,
    },
    {
        "id": "encourage_another_visit",
        "name": "Encourage Another Visit",
        "description": "Invite the customer to give the business another opportunity when appropriate.",
        "category": "recovery",
        "conditions": {"sentiments": ["negative", "very_negative"], "min_rating": 1, "max_rating": 3},
        "instructions": ["Frame the invitation as genuine, not aggressive or salesy.", "Do not pressure the customer.", "Keep it brief and proportional."],
        "compatible_strategies": ["acknowledge_feedback", "apologize_for_issue", "mention_relevant_offer"],
        "priority": 45,
    },
    {
        "id": "invite_private_conversation",
        "name": "Invite Private Conversation",
        "description": "Direct the customer to a private channel when the review contains sensitive or complex issues.",
        "category": "recovery",
        "conditions": {"sentiments": ["negative", "very_negative"], "intent_keywords": ["refund", "money back", "stolen", "scam", "lawsuit", "lawyer", "card", "charged", "wrong order", "account"]},
        "instructions": ["Acknowledge the concern briefly.", "Invite them to contact the business privately.", "Do not share any personal or account information publicly.", "Do not mention specific phone numbers or emails."],
        "compatible_strategies": ["acknowledge_feedback", "apologize_for_issue"],
        "priority": 70,
    },
    {
        "id": "keep_response_minimal",
        "name": "Keep Response Minimal",
        "description": "For simple reviews, keep the response short and proportional. No unnecessary promotions or length.",
        "category": "style",
        "conditions": {"sentiments": ["positive", "very_positive", "neutral"], "max_review_length": 30},
        "instructions": ["Keep the response to 1-2 sentences.", "Do not add promotions, recommendations, or lengthy explanations.", "Match the effort of the review."],
        "compatible_strategies": ["show_appreciation", "acknowledge_feedback"],
        "priority": 65,
    },
]

CHANNEL_POLICIES = {
    "google_review": {
        "channel": "google_review",
        "public": True,
        "max_length": 500,
        "allow_sensitive_information": False,
        "allow_private_contact": True,
    },
    "instagram": {
        "channel": "instagram",
        "public": True,
        "max_length": 300,
        "allow_sensitive_information": False,
        "allow_private_contact": True,
    },
    "facebook": {
        "channel": "facebook",
        "public": True,
        "max_length": 500,
        "allow_sensitive_information": False,
        "allow_private_contact": True,
    },
    "whatsapp": {
        "channel": "whatsapp",
        "public": False,
        "max_length": 1000,
        "allow_sensitive_information": False,
        "allow_private_contact": True,
    },
    "email": {
        "channel": "email",
        "public": False,
        "max_length": 2000,
        "allow_sensitive_information": False,
        "allow_private_contact": True,
    },
}

DEFAULT_BRAND_VOICE = {
    "tone": ["friendly", "human", "confident"],
    "avoid": ["corporate language", "excessive apologies", "fake enthusiasm"],
    "response_length": "short",
    "emoji_usage": "minimal",
}

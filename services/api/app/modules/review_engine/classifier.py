
import logging
from typing import Optional

from .classification import ReviewClassification, clamp_classification, default_subcategories
from .understanding import analyze_review, _rule_based_analysis

logger = logging.getLogger(__name__)

# Mapping LLM issue_type -> primary category
PRIMARY_CATEGORY_FROM_ISSUE_TYPE: dict[str, str] = {
    "pricing": "pricing_promotions",
    "billing": "billing_payments",
    "product_quality": "product_service",
    "product_dissatisfaction": "product_service",
    "service_quality": "complaints_dissatisfaction",
    "delivery": "delivery_fulfillment",
    "wait_time": "orders_bookings",
    "cleanliness": "complaints_dissatisfaction",
    "staff_behavior": "complaints_dissatisfaction",
    "facility_premises": "technical_issues",
    "technical_issue": "technical_issues",
    "general_complaint": "complaints_dissatisfaction",
}


def _map_intent(raw: list, customer_request: str | None, looks_question: bool) -> str:
    if not raw:
        raw = []
    lowered = [str(x).lower() for x in raw]
    if "refund_request" in lowered or "request_refund" in lowered:
        return "request_refund"
    if any("complaint" in x for x in lowered):
        return "complaint"
    if any(x in ("praise", "recommendation") for x in lowered):
        return "praise"
    if any("question" in x for x in lowered):
        return "ask_question"
    if any("suggestion" in x for x in lowered):
        return "request_change"
    if any("inquiry" in x or "question" in x for x in lowered):
        return "information_request"
    # any trailing request text -> information_request
    if customer_request and customer_request.strip():
        return "information_request"
    if looks_question:
        return "ask_question"
    # "question" is not in INTENTS; ask_question is the catch-all there.
    return "ask_question"


def _map_priority(urgency: str) -> str:
    u = (urgency or "").lower()
    if u in {"critical"}:
        return "urgent"
    if u == "high":
        return "high"
    if u == "medium":
        return "normal"
    if u == "low":
        return "low"
    return "normal"


def _map_sentiment(sentiment: str) -> str:
    """Map upstream sentiment onto the three-value SENTIMENTS set.

    Everything unrecognised becomes "mixed" -- the safe middle, which still
    lets a negative subcategory_detail or high priority set needs_attention
    upstream in clamp_classification.
    """
    s = (sentiment or "").lower()
    if s in {"very_negative", "negative"}:
        return "negative"
    if s in {"positive", "very_positive"}:
        return "positive"
    return "mixed"


async def classify_review(
    review_text: str | None,
    rating: int,
    reviewer_name: str | None,
    *,
    model: str,
    tenant_subcategories: list[str] | None = None,
    channel_id: Optional[str] = None,
    tenant_id: Optional[str] = None,
) -> ReviewClassification:
    """Produce a ReviewClassification from a review; LLM first, rule fallback."""
    text = review_text or ""
    looks_q = False
    from .understanding import looks_like_question

    looks_q = looks_like_question(text)
    sub = list(tenant_subcategories or [])

    if not model:
        raise ValueError("no model")
    try:
        analysis, _ = await analyze_review(
            text, rating, reviewer_name, model,
            tenant_id=tenant_id, channel_id=channel_id,
        )
        primary = PRIMARY_CATEGORY_FROM_ISSUE_TYPE.get(
            getattr(analysis, "issue_type", None) or "", "other"
        )
        direction = _map_intent(
            analysis.intent,
            analysis.customer_request if hasattr(analysis, "customer_request") else None,
            looks_q,
        )
        raw = {
            "primary_category": primary,
            "intent": direction,
            "sentiment": _map_sentiment(analysis.sentiment),
            "priority": _map_priority(analysis.urgency),
            "subcategory_detail": getattr(analysis, "customer_request", None),
            "summary": None,
        }
        # Pick subcategory from common Q if first in list.
        if sub:
            # naive (LLM integration could suggest)
            raw["subcategory"] = sub[0]
        else:
            raw["subcategory"] = "other"
        # Tag needs attention by priority is done by clamp
        return clamp_classification(raw, sub)
    except Exception as e:
        logger.warning("classify_review: LLM failed: %s — using rule fallback", e)

    analysis = _rule_based_analysis(text, rating)
    primary = PRIMARY_CATEGORY_FROM_ISSUE_TYPE.get(getattr(analysis, "issue_type", None) or "", "other")
    raw = {
        "primary_category": primary,
        "intent": _map_intent(analysis.intent, analysis.customer_request, looks_q),
        "sentiment": _map_sentiment(analysis.sentiment),
        "priority": _map_priority(analysis.urgency),
        "subcategory": (sub[0] if sub else "other"),
        "subcategory_detail": getattr(analysis, "customer_request", None),
        "summary": None,
    }
    return clamp_classification(raw, sub)
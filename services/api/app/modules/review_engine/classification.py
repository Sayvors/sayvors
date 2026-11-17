"""12 fixed primary issue categories plus tenant-specific subcategories.

This is the reduction of "let LLM read star-count and summary". Note that a
5-star review can be "food was cold but it's fine" — i.e. sentiment is
mixed despite the number. Therefore:
- primary_category comes from the LLM reading the review text
- sentiment comes from stance (positive / mixed / negative)
- needs_attention = needs_attention AND (priority in {high, urgent} OR
  intent in {complaint, request_refund} OR sentiment == negative)

min_rating_auto is a co-input, never the trigger.

Tenant-specific subcategories default by business_type.
"""

from dataclasses import dataclass
from typing import Optional

PRIMARY_CATEGORIES: list[str] = [
    "billing_payments",
    "product_service",
    "orders_bookings",
    "delivery_fulfillment",
    "technical_issues",
    "account_access",
    "pricing_promotions",
    "complaints_dissatisfaction",
    "returns_refunds",
    "information_inquiries",
    "technical_support_troubleshooting",
    "other",
]

SENTIMENTS: tuple[str, ...] = ("positive", "mixed", "negative")
INTENTS: tuple[str, ...] = (
    "praise", "report_problem", "ask_question", "request_refund",
    "request_change", "information_request", "complaint",
    "compliment_with_issue",
)
PRIORITIES: tuple[str, ...] = ("low", "normal", "high", "urgent")
ISSUE_STATUSES: tuple[str, ...] = (
    "new", "open", "in_progress", "resolved", "closed",
)

# Kept as a derived view for any caller that still imports the old constant.
# The canonical catalog lives in modules/verticals.py so review subcategories,
# onboarding questions and benchmarks cannot drift apart.
from ..verticals import VERTICALS, review_subcategories, resolve_vertical  # noqa: E402

DEFAULT_SUBCATEGORIES: dict[str, list[str]] = {
    key: list(v.review_subcategories) for key, v in VERTICALS.items()
}


def default_subcategories(business_type: Optional[str]) -> list[str]:
    """Resolve a stored label OR a canonical key to review subcategories.

    Exact resolution replaces the old substring match, which sent
    "E-commerce", "Non-profit" and "Retail & Shops" to ``other``.
    """
    return review_subcategories(resolve_vertical(business_type))

@dataclass
class ReviewClassification:
    primary_category: str
    subcategory: str
    subcategory_detail: Optional[str]
    intent: str
    sentiment: str
    priority: str
    needs_attention: bool
    summary: Optional[str]
    tags: list[str]

    def validate(self) -> bool:
        return (
            self.primary_category in PRIMARY_CATEGORIES
            and self.intent in INTENTS
            and self.sentiment in SENTIMENTS
            and self.priority in PRIORITIES
        )

def clamp_classification(raw: dict, tenant_subcategories: Optional[list[str]] = None) -> "ReviewClassification":
    """Clamp an LLM-derived classification to the allowed enums."""
    ts = [s.lower().replace(" ", "_") for s in (tenant_subcategories or [])]
    pc = (raw.get("primary_category") or "other").strip().lower().replace(" ", "_")
    if pc not in PRIMARY_CATEGORIES:
        pc = "other"
    # Fallbacks must themselves be valid members of the enum they clamp into.
    # "question"/"neutral" were the originals here and are in neither INTENTS nor
    # SENTIMENTS, so every defaulted row fell straight back through to an
    # invalid value and failed ReviewClassification.validate().
    intent = (raw.get("intent") or "").strip().lower()
    if intent not in INTENTS:
        intent = "ask_question"
    sentiment = (raw.get("sentiment") or "").strip().lower()
    if sentiment not in SENTIMENTS:
        sentiment = "mixed"
    priority = (raw.get("priority") or "normal").strip().lower()
    if priority not in PRIORITIES:
        priority = "normal"
    sub = (raw.get("subcategory") or "other").strip().lower().replace(" ", "_")
    # LLM gets the tenant list in its prompt; a made-up subcategory or one
    # outside the tenant's chosen set falls to 'other' so we never store a
    # string a tenant has never seen. Empty tenant list means allow any.
    if ts and sub not in ts and sub != "other":
        sub = "other"
    if not ts and len(sub) > 60:
        sub = sub[:60]
    summary = (raw.get("summary") or None)
    tags = raw.get("tags")
    if not isinstance(tags, list):
        tags = [str(tags)] if tags else []
    needs = bool(raw.get("needs_attention"))
    if sentiment == "positive" and not any(k in (raw.get("intent") or "") for k in ("complaint", "refund")):
        needs = False
    if priority in {"urgent", "high"} or sentiment == "negative":
        needs = True
    return ReviewClassification(
        primary_category=pc,
        subcategory=sub,
        subcategory_detail=(raw.get("subcategory_detail") or None),
        intent=intent,
        sentiment=sentiment,
        priority=priority,
        needs_attention=needs,
        summary=summary,
        tags=[str(t) for t in tags],
    )

def needs_review_handoff(classification: ReviewClassification) -> bool:
    """The rule that replaces `rating >= min_rating_auto`."""
    if not classification.needs_attention:
        return False
    if classification.priority in {"urgent", "high"}:
        return True
    if classification.sentiment == "negative":
        return True
    if classification.intent in {"complaint", "request_refund"} and classification.priority == "normal":
        return True
    return False
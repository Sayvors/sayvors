"""Deterministic issue extraction from review text + analysis.

No LLM involved: the same complaint must always yield the same issues,
so strategy enforcement and fulfillment validation have a stable target.
"""
import logging
import re

from .schemas import ExtractedIssue, ReviewAnalysis

logger = logging.getLogger(__name__)

# (pattern, key, label, detail-template, keyword-variants)
PATTERNS: list[tuple[str, str, str, str, list[str]]] = [
    (
        r"(\d+)\s*(?:-|–)?\s*(min|mins|minute|minutes|hr|hrs|hour|hours)",
        "wait_time",
        "Long wait",
        "{n} {unit} wait",
        ["wait", "waiting", "waited"],
    ),
    (
        r"\b(cold|lukewarm)\b.{0,20}\b(food|dish|meal|pizza|order)\b|\b(food|dish|meal|pizza|order)\b.{0,20}\b(cold|lukewarm)\b",
        "food_temperature",
        "Cold food",
        "cold food",
        ["cold"],
    ),
    (
        r"\b(raw|undercooked|burnt|burned|overcooked|soggy|stale|spoiled)\b",
        "food_quality",
        "Food quality",
        "{m} food",
        [],
    ),
    (
        r"\b(rude|disrespectful|dismissive|ignored|ignoring|unhelpful|unprofessional|attitude|yelled|scolded)\b",
        "staff_behavior",
        "Staff behavior",
        "{m} staff interaction",
        [],
    ),
    (
        r"\b(late|delayed|never arrived|took forever|slow delivery)\b|\bdelivery\b.{0,20}\b(late|slow|hour|hours)\b",
        "delivery",
        "Delivery problem",
        "delivery problem",
        ["delivery", "late", "arrived"],
    ),
    (
        r"\b(charged twice|double charg\w*|charged (me |us )?too much|wrong (amount|bill)|unexpected charg\w*|payment (failed|declined|error)|invoice (is |was )?(wrong|incorrect)|billing error|charged for .*not order)\b",
        "billing",
        "Billing issue",
        "billing issue",
        ["charge", "charged", "bill", "refund", "payment", "invoice"],
    ),
    (
        r"\b(dirty|filthy|unclean|hygiene|roach|cockroach|hair in)\b",
        "cleanliness",
        "Cleanliness",
        "cleanliness issue",
        ["dirty", "clean"],
    ),
    (
        r"\b(noisy|loud|music too|too crowded|noisy)\b",
        "ambience",
        "Ambience",
        "ambience issue",
        ["noise", "noisy", "loud"],
    ),
    (
        r"\b(too expensive|overpriced|pricey|costly|prices? (is |are |feels? )?(so |too )?high|high prices?|not worth (the|its|their) (price|money|cost)|costs too much)\b",
        "pricing",
        "Pricing concern",
        "price feels too high",
        ["price", "pricing", "expensive", "cost", "costly", "worth"],
    ),
]

CHURN_SIGNALS = [
    "never coming back",
    "never again",
    "never return",
    "won't be back",
    "will not return",
    "done with",
    "last visit",
    "lost a customer",
    "cancel",
]

# Internal key → natural customer-facing equivalents. Coverage accepts these;
# the internal key itself must NEVER appear in a reply (taxonomy leak).
ISSUE_SEMANTICS: dict[str, list[str]] = {
    "product_dissatisfaction": ["didn't meet expectations", "didn’t meet expectations",
                                "not what you expected", "disappointed", "let you down",
                                "fell short", "not happy with", "frustrat",
                                "didn't work for you", "hasn't worked", "not right for you"],
    "product_quality": ["quality", "broken", "defective", "not working",
                        "stopped working", "doesn't work", "faulty"],
    "service_quality": ["service", "experience", "visit"],
    "delivery": ["delivery", "deliver", "arrived", "late", "shipping", "order"],
    "wait_time": ["wait", "waiting", "waited", "slow", "took so long", "took long"],
    "cleanliness": ["dirty", "clean", "filthy", "hygiene"],
    "staff_behavior": ["rude", "rudeness", "staff", "treated", "treatment", "unprofessional"],
    "billing": ["bill", "billing", "charge", "charged", "payment", "refund", "price", "cost", "overcharged"],
    "pricing": ["price", "pricing", "expensive", "costly", "cost", "overpriced", "worth", "value", "expensive"],
    "food_temperature": ["cold", "hot", "lukewarm", "temperature"],
    "food_quality": ["quality", "taste", "undercooked", "burnt", "raw", "soggy"],
    "ambience": ["noise", "noisy", "loud", "crowded"],
    "product_reference": [],
}


def detect_churn(review_text: str) -> bool:
    text = (review_text or "").lower()
    return any(sig in text for sig in CHURN_SIGNALS)


def extract_issues(review_text: str, analysis: ReviewAnalysis) -> list[ExtractedIssue]:
    """Extract concrete complaint facts. Deterministic for the same input."""
    text = review_text or ""
    lower = text.lower()
    issues: list[ExtractedIssue] = []
    seen: set[str] = set()

    for pattern, key, label, detail_tpl, extra_kw in PATTERNS:
        m = re.search(pattern, lower)
        if not m or key in seen:
            continue
        seen.add(key)
        detail = detail_tpl
        keywords = list(extra_kw)
        if "{n}" in detail_tpl:
            n = next((g for g in m.groups() if g and g.isdigit()), "")
            unit = "minutes" if any(u in (m.group(0) or "") for u in ("min",)) else "hours"
            detail = detail_tpl.format(n=n, unit=unit)
            if n:
                keywords += [n, f"{n} minutes" if unit == "minutes" else f"{n} hours",
                             f"{n}-minute" if unit == "minutes" else f"{n}-hour"]
        if "{m}" in detail_tpl:
            matched = next((g for g in m.groups() if g), "")
            detail = detail_tpl.format(m=matched)
            keywords.append(matched)
        # The exact matched span is always a valid keyword
        span = m.group(0).strip()
        if span and span not in keywords:
            keywords.append(span)
        issues.append(ExtractedIssue(
            key=key, label=label, detail=detail,
            keywords=[k for k in dict.fromkeys(keywords) if k][:12],
            semantic=ISSUE_SEMANTICS.get(key, []),
        ))

    # Fall back to the analysis issue_type so there is always a target
    # when the review is negative but matches no concrete pattern.
    if not issues and analysis.issue_type and analysis.sentiment in ("negative", "very_negative"):
        label = analysis.issue_type.replace("_", " ")
        issues.append(ExtractedIssue(
            key=analysis.issue_type, label=label.title(),
            detail=label, keywords=[w for w in label.split() if len(w) > 3],
            generic=True,
            semantic=ISSUE_SEMANTICS.get(analysis.issue_type, []),
        ))

    # Product reference contributes searchable keywords when present
    if analysis.product_reference:
        ref = analysis.product_reference.strip()
        if ref and not any(ref.lower() in " ".join(i.keywords) for i in issues):
            issues.append(ExtractedIssue(
                key="product_reference", label="Mentioned item", detail=ref,
                keywords=[ref] + [w for w in ref.split() if len(w) > 3],
                generic=True,
            ))

    return issues

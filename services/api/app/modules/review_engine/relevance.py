"""Business-relevance assessment: is this review even about THIS business?

A review mentioning a specific product/item that matches nothing in the
business domain (location categories, services, databank) is flagged as
potentially irrelevant — e.g. a pizza complaint at an AI company.

Rules:
- No mentioned product → "uncertain" (generic complaints can't be judged;
  the normal pipeline proceeds untouched).
- Mentioned product matches domain → "on_topic" with evidence.
- Mentioned product matches nothing → "off_topic" with reason.
"""
import logging
import re

logger = logging.getLogger(__name__)


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]{2,}", (text or "").lower())]


# Generic nouns that discriminate nothing — a review about "the product"
# or "the service" alone can never be judged off-topic.
NEUTRAL_WORDS = frozenset({
    "the", "a", "an", "and", "or", "for", "with", "this", "that", "your",
    "our", "their", "its", "my",
    "product", "products", "service", "services", "item", "items", "thing",
    "things", "order", "orders", "place", "store", "company", "business",
    "app", "apps", "experience",
})

# Minimum configured domain size — below this, flagging would be noise.
MIN_DOMAIN_TERMS = 5


def _term_hit(term: str, domain_words: set[str]) -> bool:
    """Whole-word or stem-tolerant match of one term against domain words."""
    term = term.lower()
    if term in domain_words:
        return True
    stem = term[:5] if len(term) >= 5 else term
    return any(
        len(sw) >= 4 and (sw.startswith(stem) or stem.startswith(sw[:5]))
        for sw in domain_words
    )


async def resolve_business_domain(
    channel_id: str | None, tenant_id: str, db
) -> dict:
    """Collect business-domain terms from everything the tenant configured.

    Delegates to the Retrieval Layer (domain vocabulary provider) — this
    module owns relevance *assessment* only, never storage access. Returns
    {"terms": [...], "sources": {...}, "not_offered": [...]}, where
    `not_offered` (the tenant's explicit does-NOT-sell list) is deliberately
    NOT part of `terms`.
    """
    try:
        from ..retrieval.layer import domain_vocabulary

        return await domain_vocabulary(db, tenant_id, channel_id)
    except Exception as e:
        if "UndefinedTableError" in type(e).__name__ or "does not exist" in str(e):
            logger.debug("Business domain resolution failed (table missing): %s", e)
        else:
            logger.warning("Business domain resolution failed: %s", e)
        return {"terms": [], "sources": {}, "not_offered": []}


def assess_relevance(
    review_text: str,
    analysis,
    domain: dict,
) -> dict:
    """Verdict dict: {verdict, reason, evidence, matched_terms}."""
    product_ref = ((analysis.product_reference or "").strip()) if analysis else ""
    domain_words = set((domain or {}).get("terms", []))
    not_offered_words = set((domain or {}).get("not_offered", []))

    if not product_ref:
        return {
            "verdict": "uncertain",
            "reason": "No specific product mentioned — cannot judge relevance; normal pipeline.",
            "evidence": "",
            "matched_terms": [],
        }
    ref_words = [w for w in _words(product_ref) if w not in NEUTRAL_WORDS]
    if not ref_words:
        return {
            "verdict": "uncertain",
            "reason": "Mentioned item is too generic to judge — normal pipeline.",
            "evidence": "",
            "matched_terms": [],
        }
    # Explicit owner exclusion beats everything: the tenant said they do NOT
    # sell this. Evaluated before the domain-size gate — direct tenant intent
    # needs no minimum corpus.
    excluded = [w for w in ref_words if _term_hit(w, not_offered_words)] if not_offered_words else []
    if excluded:
        return {
            "verdict": "off_topic",
            "reason": (
                f"Mentioned item '{product_ref}' is on the business's explicit "
                f"does-not-sell list — review is about something else."
            ),
            "evidence": f"'{product_ref}' ↔ not-offered: {', '.join(sorted(set(excluded)))}",
            "matched_terms": [],
        }
    if len(domain_words) < MIN_DOMAIN_TERMS:
        return {
            "verdict": "uncertain",
            "reason": "Too little business domain configured — cannot judge relevance.",
            "evidence": "",
            "matched_terms": [],
        }
    matched = [w for w in ref_words if _term_hit(w, domain_words)]
    if matched:
        return {
            "verdict": "on_topic",
            "reason": f"Mentioned item matches business domain ({', '.join(matched)}).",
            "evidence": f"'{product_ref}' ↔ {', '.join(sorted(set(matched)))}",
            "matched_terms": sorted(set(matched)),
        }
    return {
        "verdict": "off_topic",
        "reason": (
            f"Mentioned item '{product_ref}' matches nothing in the configured business "
            f"domain — review might be irrelevant to this business."
        ),
        "evidence": f"'{product_ref}' vs {len(domain_words)} domain terms, 0 overlap",
        "matched_terms": [],
    }


def apply_retrieval_corroboration(verdict: dict, has_product_data: bool) -> dict:
    """Databank evidence overrides the word-overlap verdict.

    If the tenant's own databank contains the mentioned item, the review is
    about their business no matter what the domain terms say.
    """
    if verdict.get("verdict") == "off_topic" and has_product_data:
        return {
            "verdict": "on_topic",
            "reason": "Databank contains the mentioned item — relevance confirmed by retrieval.",
            "evidence": "product search returned hits",
            "matched_terms": verdict.get("matched_terms", []),
        }
    return verdict

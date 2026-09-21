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

    Sources: tenant business context (category/sells/description), location
    profiles (categories + description), channel services, channel display
    name, databank names + document filenames. Tenant-wide (not per-channel
    exact) — robust when links are missing.

    The tenant's explicit "does NOT sell" list is returned separately under
    `not_offered` and is deliberately NOT part of `terms`: those words must
    never count as evidence that a review is on-topic.
    """
    from sqlalchemy import select

    terms: set[str] = set()
    not_offered: set[str] = set()
    sources: dict[str, int] = {}
    try:
        from ..channels.models import BusinessService, Channel
        from ..locations.models import LocationProfile
        from ..profile.service import get_business_context
        from ..rag.models import Databank, Document

        # Each source is queried independently — a missing table or
        # aborted transaction in one must NOT poison the session for the
        # rest of the pipeline (the later INSERT of review_response_logs).
        async def _safe_execute(stmt, label: str):
            try:
                return await db.execute(stmt)
            except Exception as e:
                # Missing table on dev DBs (e.g. location_profiles) is expected until migrated —
                # debug level so it doesn't spam every review request.
                if "UndefinedTableError" in type(e).__name__ or "does not exist" in str(e):
                    logger.debug("Business domain %s skipped (table missing): %s", label, e)
                else:
                    logger.warning("Business domain %s failed: %s", label, e)
                try:
                    await db.rollback()
                except Exception:
                    pass
                return None

        # Tenant business context FIRST — the owner's own identity of the
        # company (category, what they sell, 1-line description) is the most
        # direct signal of what the business is. The explicit "does NOT sell"
        # list is kept OUT of `terms` — those words must never count as
        # on-topic evidence.
        try:
            ctx = await get_business_context(tenant_id, db)
        except Exception as e:
            logger.debug("Business context unavailable: %s", e)
            ctx = {}
        if ctx:
            terms.update(_words(ctx.get("business_type") or ""))
            terms.update(_words(ctx.get("business_sells") or ""))
            terms.update(_words(ctx.get("business_description") or ""))
            not_offered.update(_words(ctx.get("business_doesnt_sell") or ""))
            sources["business_context"] = sum(1 for v in ctx.values() if v)

        res = await _safe_execute(select(LocationProfile).where(LocationProfile.user_id == tenant_id), "location_profiles")
        profiles = res.scalars().all() if res is not None else []
        for p in profiles:
            cats = p.categories or {}
            if isinstance(cats, dict):
                if cats.get("primary"):
                    terms.update(_words(str(cats["primary"])))
                for extra in cats.get("additional") or []:
                    terms.update(_words(str(extra)))
            terms.update(_words(p.description or ""))
        if profiles:
            sources["location_profiles"] = len(profiles)

        if channel_id:
            res = await _safe_execute(select(BusinessService).where(BusinessService.channel_id == channel_id), "channel_services")
            services = res.scalars().all() if res is not None else []
            for s in services:
                terms.update(_words(s.name or ""))
                terms.update(_words(s.category or ""))
                terms.update(_words(s.description or ""))
            if services:
                sources["channel_services"] = len(services)

            res = await _safe_execute(
                select(Channel.display_name).where(Channel.id == channel_id, Channel.user_id == tenant_id),
                "channel",
            )
            ch = res.scalar_one_or_none() if res is not None else None
            if ch:
                terms.update(_words(ch))
                sources["channel_name"] = 1

        res = await _safe_execute(select(Databank).where(Databank.user_id == tenant_id).limit(10), "databanks")
        banks = res.scalars().all() if res is not None else []
        for b in banks:
            terms.update(_words(b.name or ""))
        if banks:
            sources["databanks"] = len(banks)
            res = await _safe_execute(
                select(Document.filename).where(Document.databank_id.in_([b.id for b in banks])).limit(50),
                "documents",
            )
            rows = res.all() if res is not None else []
            for (filename,) in rows:
                cleaned = re.sub(r"\.[a-z0-9]+$", "", filename or "")
                terms.update(w for w in _words(cleaned) if w not in {"databank", "data", "csv", "final", "new"})
            sources["documents"] = len(rows)
    except Exception as e:
        if "UndefinedTableError" in type(e).__name__ or "does not exist" in str(e):
            logger.debug("Business domain resolution failed (table missing): %s", e)
        else:
            logger.warning("Business domain resolution failed: %s", e)
        try:
            await db.rollback()
        except Exception:
            pass
    return {"terms": sorted(terms), "sources": sources,
            "not_offered": sorted(not_offered)}


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

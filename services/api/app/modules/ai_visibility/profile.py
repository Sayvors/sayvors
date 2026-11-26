"""Tenant-scoped business facts used to classify a branch and choose questions.

Merchant overrides win over Google-synced values because they represent what
the owner says is true today. Every field retained in the profile is also
reported through ``source_fields`` so generated questions can explain their
inputs without exposing private data.
"""
from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..analytics.models import ConversationInsight, ReviewInsight
from ..catalog.models import CatalogItem
from ..channels.models import BusinessService, Channel
from ..locations.models import LocationBusinessOverride, LocationProfile
from ..memory.service import scrub_pii
from ..profile.models import BusinessProfile
from ..users.models import User
from . import search, sources
from .search import SearchResult
from .taxonomy import classify_industry

MAX_WEBSITE_CONTEXT_CHARS = 4000
MAX_PUBLIC_CONTEXT_PAGES = 2
MAX_PUBLIC_CONTEXT_CHARS = 30_000
GENERIC_NAME_WORDS = {
    "company",
    "branch",
    "business",
    "location",
    "store",
    "shop",
    "office",
}
MAX_DECLARED_SERVICES = 20
MAX_PRODUCTS = 20
MAX_REVIEW_SAMPLE = 50
MAX_CUSTOMER_QUESTIONS = 20


def _metadata(channel: Any) -> dict:
    try:
        value = json.loads(getattr(channel, "metadata_json", None) or "{}")
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _categories(value: Any) -> dict:
    if not isinstance(value, dict):
        return {}
    out: dict = {}
    for key in ("category", "primary"):
        if value.get(key):
            out[key] = str(value[key])
    for key in ("subcategories", "sub_subcategories", "additional"):
        items = value.get(key)
        if isinstance(items, list):
            out[key] = [str(item) for item in items if str(item).strip()]
    return out


def _services(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str):
            label = item.strip()
        elif isinstance(item, dict):
            label = str(item.get("label") or item.get("name") or "").strip()
        else:
            continue
        if label and label not in out:
            out.append(label)
    return out


def _names(value: Any, *, limit: int = MAX_CUSTOMER_QUESTIONS) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str):
            name = item.strip()
        elif isinstance(item, dict):
            name = str(
                item.get("name")
                or item.get("question")
                or item.get("topic")
                or item.get("intent")
                or ""
            ).strip()
        else:
            continue
        if name and name not in out:
            out.append(name)
            if len(out) >= limit:
                break
    return out


def _scrub_question(
    value: str,
    *,
    reviewer_name: str | None = None,
    protected_terms: set[str] | None = None,
) -> str:
    """Scrub identifiers, known reviewer names, handles, and person-name cues."""
    question = scrub_pii(value)
    protected = {term.casefold() for term in (protected_terms or set())}
    protected.update({
        "google", "maps", "whatsapp", "facebook", "instagram", "youtube",
        "tiktok", "linkedin", "chatgpt", "gemini", "perplexity",
    })
    reviewer = (reviewer_name or "").strip()
    if reviewer:
        question = re.sub(
            rf"(?<!\w){re.escape(reviewer)}(?!\w)",
            "[customer]",
            question,
            flags=re.IGNORECASE,
        )
        for component in re.findall(r"\w{2,}", reviewer):
            question = re.sub(
                rf"(?<!\w){re.escape(component)}(?!\w)",
                "[customer]",
                question,
                flags=re.IGNORECASE,
            )
    question = re.sub(r"(?<!\w)@[A-Za-z0-9_.]{2,}", "[customer]", question)

    def redact_full_name(match: re.Match) -> str:
        phrase = match.group(0)
        first = phrase.split()[0].casefold()
        if first in {
            "can", "could", "does", "did", "is", "was", "will", "would",
            "should", "has", "have", "to", "for", "from", "with", "by",
            "about", "ask", "contact", "email", "call", "what", "where",
            "when", "why", "how", "who", "which",
        } or phrase.casefold() in {
            "google maps", "google business", "whatsapp", "facebook",
            "instagram", "youtube", "tiktok", "linkedin", "chatgpt",
            "gemini", "perplexity",
        }:
            return phrase
        return phrase if phrase.casefold() in protected else "[customer]"

    question = re.sub(
        r"\b[A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,})+\b",
        redact_full_name,
        question,
    )

    def redact_person_cue(match: re.Match) -> str:
        name = match.group(1)
        return match.group(0) if name.casefold() in protected else f"{match.group(0)[:-len(name)]}[customer]"

    question = re.sub(
        r"\b(?i:can|could|does|did|is|was|will|would|should|has|have|to|for|from|with|by|about|ask|contact|email|call)\s+([A-Z][a-z]{2,})\b",
        redact_person_cue,
        question,
    )
    return " ".join(question.split())


async def _workspace_context(db: AsyncSession, tenant_id: str) -> tuple[Any, Any]:
    user = (
        await db.execute(select(User).where(User.id == tenant_id))
    ).scalar_one_or_none()
    card = (
        await db.execute(
            select(BusinessProfile).where(BusinessProfile.user_id == tenant_id)
        )
    ).scalar_one_or_none()
    return user, card


async def _declared_services(db: AsyncSession, channel_id: str) -> list[dict]:
    rows = (
        await db.execute(
            select(BusinessService)
            .where(
                BusinessService.channel_id == channel_id,
                BusinessService.declared.is_(True),
                BusinessService.is_offered.is_(True),
            )
            .order_by(BusinessService.created_at.desc())
            .limit(MAX_DECLARED_SERVICES)
        )
    ).scalars().all()
    return [
        {"name": row.name, "description": row.description}
        for row in rows
    ]


async def _products(db: AsyncSession, tenant_id: str) -> list[dict]:
    rows = (
        await db.execute(
            select(CatalogItem)
            .where(CatalogItem.tenant_id == tenant_id, CatalogItem.active.is_(True))
            .order_by(CatalogItem.sort_order, CatalogItem.created_at.desc())
            .limit(MAX_PRODUCTS)
        )
    ).scalars().all()
    return [
        {"name": row.name, "description": row.description}
        for row in rows
    ]

COUNTRY_NAMES = {
    "saudi arabia",
    "pakistan",
    "united arab emirates",
    "uae",
    "oman",
    "qatar",
    "kuwait",
    "bahrain",
}


def _derive_locality(address: Any, service_area: Any, country: Any) -> str:
    parts = [
        part.strip()
        for part in str(address or "").split(",")
        if part.strip() and not part.strip().isdigit()
    ]
    if parts:
        locality = parts[-1]
        if len(parts) >= 3 and locality.casefold() in COUNTRY_NAMES:
            locality = parts[-2]
        return locality
    if isinstance(service_area, list) and service_area:
        return str(service_area[0]).strip()
    return str(country or "").strip()


def build_branch_facts(channel: Any, profile: Any, override: Any) -> dict:
    """Merge Google facts and merchant overrides into one bounded profile."""
    meta = _metadata(channel)
    override_categories = _categories(getattr(override, "categories", None))
    profile_categories = _categories(getattr(profile, "categories", None))
    metadata_categories = _categories(meta.get("categories"))
    if meta.get("category") and "category" not in metadata_categories:
        metadata_categories["category"] = str(meta["category"])
    hours = getattr(override, "hours", None) or getattr(profile, "hours", None) or meta.get("hours") or {}
    service_area = (
        getattr(profile, "service_area", None)
        or meta.get("service_area")
        or []
    )
    attributes = (
        getattr(profile, "attributes", None)
        or meta.get("attributes")
        or {}
    )
    address = meta.get("address") or meta.get("locality")
    locality = (
        meta.get("locality")
        or meta.get("city")
        or _derive_locality(address, service_area, meta.get("country"))
    )
    facts = {
        "name": getattr(override, "name", None) or getattr(channel, "display_name", ""),
        "address": address,
        "locality": locality or None,
        "country": meta.get("country"),
        "region_code": meta.get("region_code"),
        "phone": meta.get("phone"),
        "website": meta.get("website"),
        "maps_url": meta.get("maps_url") or meta.get("mapsUri") or meta.get("mapsUrl"),
        "categories": override_categories or profile_categories or metadata_categories,
        "description": getattr(profile, "description", None) or meta.get("description"),
        "services": _services(getattr(override, "services", None) or meta.get("services")),
        "hours": hours if isinstance(hours, dict) else {},
        "service_area": list(service_area) if isinstance(service_area, list) else [],
        "attributes": dict(attributes) if isinstance(attributes, dict) else {},
        "opening_date": getattr(profile, "opening_date", None),
    }
    facts["source_fields"] = tuple(
        key for key, value in facts.items() if value not in (None, "", [], {})
    )
    return facts


async def _customer_voice(
    db: AsyncSession,
    tenant_id: str,
    channel_id: str,
    protected_terms: set[str] | None = None,
) -> tuple[list[str], list[str], list[str]]:
    reviews = (
        await db.execute(
            select(ReviewInsight)
            .where(
                ReviewInsight.user_id == tenant_id,
                ReviewInsight.channel_id == channel_id,
                ReviewInsight.enrichment_status == "done",
                ReviewInsight.skipped.is_(False),
                ReviewInsight.removed_at.is_(None),
            )
            .order_by(ReviewInsight.created_at.desc())
            .limit(MAX_REVIEW_SAMPLE)
        )
    ).scalars().all()
    themes: list[str] = []
    questions: list[str] = []
    for row in reviews:
        for value in (row.topics, row.products, row.problems):
            for name in _names(value or []):
                if name not in themes:
                    themes.append(name)
        meaning = row.meaning if isinstance(row.meaning, dict) else {}
        for raw_question in _names(meaning.get("asks") or []):
            question = _scrub_question(
                raw_question,
                reviewer_name=row.reviewer_name,
                protected_terms=protected_terms,
            )
            if question and question not in questions:
                questions.append(question)
    insight = (
        await db.execute(
            select(ConversationInsight)
            .where(ConversationInsight.tenant_id == tenant_id)
            .order_by(ConversationInsight.window_end.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    intents: list[str] = []
    if insight and isinstance(insight.insights, dict):
        payload = insight.insights
        for raw_question in _names(payload.get("top_questions") or []):
            question = _scrub_question(raw_question, protected_terms=protected_terms)
            if question and question not in questions:
                questions.append(question)
        for topic in _names(payload.get("topics") or []):
            if topic not in themes:
                themes.append(topic)
        intents = _names(payload.get("intents") or [])
    return (
        themes[:MAX_CUSTOMER_QUESTIONS],
        questions[:MAX_CUSTOMER_QUESTIONS],
        intents[:MAX_CUSTOMER_QUESTIONS],
    )


async def load_branch_facts(
    db: AsyncSession, tenant_id: str, channel_id: str
) -> dict:
    """Load branch facts with tenant scope and merchant-override precedence."""
    channel = (
        await db.execute(
            select(Channel).where(
                Channel.id == channel_id,
                Channel.user_id == tenant_id,
            )
        )
    ).scalar_one_or_none()
    if channel is None:
        raise ValueError("channel_not_owned")
    meta = _metadata(channel)
    listing_id = str(meta.get("location_id") or channel.listing_key or "")
    profile = (
        await db.execute(
            select(LocationProfile).where(
                LocationProfile.user_id == tenant_id,
                LocationProfile.listing_id == listing_id,
            )
        )
    ).scalar_one_or_none()
    override = (
        await db.execute(
            select(LocationBusinessOverride).where(
                LocationBusinessOverride.user_id == tenant_id,
                LocationBusinessOverride.listing_id == listing_id,
            )
        )
    ).scalar_one_or_none()
    facts = build_branch_facts(channel, profile, override)
    user, card = await _workspace_context(db, tenant_id)
    declared = await _declared_services(db, channel_id)
    products = await _products(db, tenant_id)
    protected_text = " ".join(
        str(value or "")
        for value in (
            facts.get("name"),
            facts.get("description"),
            facts.get("address"),
            facts.get("locality"),
            facts.get("categories"),
            facts.get("services"),
            getattr(user, "business_name", None),
            getattr(card, "domain", None),
        )
    )
    protected_text += " " + " ".join(
        str(row.get("name") or "") for row in declared + products
    )
    protected_terms = set(re.findall(r"\w{3,}", protected_text.casefold()))
    themes, customer_questions, customer_intents = await _customer_voice(
        db, tenant_id, channel_id, protected_terms=protected_terms
    )
    declared_names = [row["name"] for row in declared if row.get("name")]
    facts["services"] = list(dict.fromkeys(facts["services"] + declared_names))
    facts["declared_services"] = declared
    facts["products"] = products
    facts["workspace_business_type"] = (
        getattr(user, "business_type", None) or getattr(card, "domain", None)
    )
    facts["vertical_key"] = getattr(user, "vertical_key", None)
    facts["business_description"] = getattr(user, "business_description", None)
    facts["business_sells"] = getattr(user, "business_sells", None)
    facts["not_offered"] = " ".join(
        value
        for value in (
            getattr(user, "business_doesnt_sell", None),
            getattr(card, "not_offered_and_policies", None),
        )
        if value
    )
    facts["offering_text"] = getattr(card, "products_services", None)
    facts["audience_languages"] = getattr(card, "audience_languages", None)
    facts["review_themes"] = themes
    facts["customer_questions"] = customer_questions
    facts["customer_intents"] = customer_intents
    if not facts["description"]:
        facts["description"] = (
            getattr(user, "business_description", None)
            or getattr(card, "summary", None)
        )
    if not facts["categories"]:
        category = (
            getattr(user, "business_type", None)
            or getattr(card, "domain", None)
            or getattr(user, "vertical_key", None)
        )
        if category:
            facts["categories"] = {"primary": str(category)}
    facts["source_fields"] = tuple(
        key for key, value in facts.items() if value not in (None, "", [], {})
    )
    return facts


def _distinctive_tokens(branch: dict) -> set[str]:
    name_tokens = {
        token
        for token in re.findall(
            r"[a-z0-9\u0600-\u06ff]{4,}", str(branch.get("name") or "").casefold()
        )
        if token not in GENERIC_NAME_WORDS
    }
    locality_text = " ".join(
        str(branch.get(key) or "")
        for key in ("address", "locality", "service_area")
    )
    locality_tokens = set(
        re.findall(r"[a-z0-9\u0600-\u06ff]{4,}", locality_text.casefold())
    )
    return (name_tokens - locality_tokens) or name_tokens


def _context_row(row: Any, *, max_chars: int) -> dict:
    return {
        "url": row.canonical_url or row.url,
        "title": row.title,
        "description": row.snippet,
        "excerpt": (row.excerpt or "")[:max_chars],
    }


async def collect_public_context(tenant_id: str, branch: dict) -> dict:
    """Read the branch website and relevant public pages without persisting rows.

    The returned snapshot is bounded and stored with the query set. Failures
    are explicit uncertainties; they never become invented business facts.
    """
    context: dict = {
        "website": None,
        "public_results": [],
        "uncertainties": [],
    }
    website = str(branch.get("website") or "").strip()
    if website:
        try:
            row, _stats = await sources.fetch_source(
                f"context:{tenant_id}",
                0,
                SearchResult(website, "Branch website", ""),
            )
            if row.excerpt:
                context["website"] = _context_row(
                    row, max_chars=MAX_WEBSITE_CONTEXT_CHARS
                )
            else:
                context["uncertainties"].append("website_unavailable")
        except Exception:
            context["uncertainties"].append("website_unavailable")
    else:
        context["uncertainties"].append("website_missing")

    if branch.get("description") and context["website"]:
        return context
    name = str(branch.get("name") or "").strip()
    locality = str(branch.get("locality") or branch.get("address") or "").strip()
    query = " ".join(part for part in (name, locality) if part)
    if not query:
        context["uncertainties"].append("public_search_skipped")
        return context
    tokens = _distinctive_tokens(branch)
    try:
        rows = await search.search_public_web(
            tenant_id, query, distinctive=tokens
        )
    except Exception:
        context["uncertainties"].append("public_search_unavailable")
        return context
    relevant = [
        row
        for row in rows
        if not tokens or search._row_matches_tokens(row, tokens)
    ]
    seen = {context["website"]["url"]} if context["website"] else set()
    budget = MAX_PUBLIC_CONTEXT_CHARS
    for row in relevant:
        if len(context["public_results"]) >= MAX_PUBLIC_CONTEXT_PAGES or budget <= 0:
            break
        if search.canonical_url(row.url) in seen:
            continue
        try:
            fetched, _stats = await sources.fetch_source(
                f"context:{tenant_id}",
                len(context["public_results"]) + 1,
                row,
            )
        except Exception:
            continue
        if not fetched.excerpt:
            continue
        snapshot = _context_row(fetched, max_chars=min(MAX_WEBSITE_CONTEXT_CHARS, budget))
        context["public_results"].append(snapshot)
        seen.add(search.canonical_url(fetched.url))
        budget -= len(snapshot["excerpt"])
    if not context["public_results"]:
        context["uncertainties"].append("no_relevant_public_pages")
    return context


async def load_business_profile(
    db: AsyncSession, tenant_id: str, channel_id: str
) -> dict:
    """Assemble the complete, reproducible classifier input for one branch."""
    facts = await load_branch_facts(db, tenant_id, channel_id)
    context = await collect_public_context(tenant_id, facts)
    website = context.get("website") or {}
    facts["website_title"] = website.get("title")
    facts["website_description"] = website.get("description")
    facts["public_context"] = context
    match = classify_industry(facts)
    facts["classification"] = {
        "industry": match.industry,
        "business_type": match.business_type,
        "subcategories": list(match.subcategories),
        "confidence": match.confidence,
        "matched_signals": list(match.matched_signals),
        "uncertainties": list(match.uncertainties),
    }
    facts["uncertainties"] = list(
        dict.fromkeys(list(context.get("uncertainties") or []) + list(match.uncertainties))
    )
    facts["source_fields"] = tuple(
        key for key, value in facts.items() if value not in (None, "", [], {})
    )
    return facts
